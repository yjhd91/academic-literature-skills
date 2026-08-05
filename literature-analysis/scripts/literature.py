#!/usr/bin/env python3
"""Literature analysis pipeline: fetch PubMed records and build extraction/screening files.

The semantic extraction and screening are performed by the agent following SKILL.md.
This script handles data plumbing (fetch + save) and deterministic keyword triage.

Commands:
  fetch --query "QUERY" [--max N] --out results.json
  template --in results.json --out template.csv [--fields "study design,sample size,..."]
  screen --in results.json --out triage.csv [--include "kw1|kw2"] [--exclude "kw1|kw2"]

Examples:
  python literature.py fetch --query "radiomics lung cancer prognosis" --max 10 --out results.json
  python literature.py template --in results.json --out template.csv
  python literature.py screen --in results.json --out triage.csv --include "external validation" --exclude "review|animal"
"""

import argparse
import collections
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

SKILLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PUBMED_SCRIPT = os.path.join(SKILLS_ROOT, "pubmed-live", "scripts", "pubmed.py")
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OPENALEX = "https://api.openalex.org/works"
CROSSREF = "https://api.crossref.org/works"
TOOL = "codex-literature-analysis"

DEFAULT_FIELDS = [
    "study design",
    "population / sample size",
    "imaging modality / data",
    "method / model",
    "validation",
    "key results / performance",
    "limitations",
]

OVERVIEW_FIELDS = [
    "study design",
    "population",
    "sample size",
    "imaging modality / data",
    "method / model",
    "validation",
    "performance metrics",
    "main findings",
    "limitations",
    "evidence level",
    "citation count",
    "open access status",
    "topic relevance",
    "decision",
    "reason",
    "evidence",
]

AUTO_FILL = {"citation count": "citation_count", "open access status": "oa_status"}


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": TOOL})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def http_get_retry(url, tries=3, timeout=30):
    """GET with polite backoff for 429/timeout (failure-signal handling)."""
    last = None
    for i in range(tries):
        try:
            return http_get(url, timeout=timeout)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 429:
                time.sleep(2 * (i + 1))
                continue
            raise
        except Exception as exc:  # timeout / connection error
            last = exc
            time.sleep(2 * (i + 1))
    raise last


def first_str(v):
    """Return the first element of a list value, or the scalar; empty string if None."""
    if isinstance(v, list):
        return v[0] if v else ""
    return v or ""


def mesh_lookup(concept, max_mesh=3):
    """Return up to max_mesh preferred MeSH descriptor names for a concept."""
    params = {"db": "mesh", "term": concept, "retmode": "json", "retmax": max_mesh, "tool": TOOL}
    url = EUTILS + "/esearch.fcgi?" + urllib.parse.urlencode(params)
    data = json.loads(http_get(url))
    ids = data.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    time.sleep(0.4)
    url = EUTILS + "/esummary.fcgi?" + urllib.parse.urlencode(
        {"db": "mesh", "id": ",".join(ids), "retmode": "json", "tool": TOOL}
    )
    summ = json.loads(http_get(url)).get("result", {})
    names = []
    for uid in ids:
        item = summ.get(uid)
        if not item:
            continue
        terms = item.get("ds_meshterms") or []
        if terms:
            names.append(terms[0])
    return names


def search_count(query):
    params = {"db": "pubmed", "term": query, "retmode": "json", "retmax": 0, "tool": TOOL}
    url = EUTILS + "/esearch.fcgi?" + urllib.parse.urlencode(params)
    data = json.loads(http_get(url))
    return data.get("esearchresult", {}).get("count", "0")


def validate_query(query):
    """Lightweight syntax checks for a PubMed query."""
    issues = []
    if query.count("(") != query.count(")"):
        issues.append("unbalanced parentheses")
    if query.count('"') % 2:
        issues.append("unbalanced double quotes")
    if re.search(r"\[dp\]", query) and not re.search(r'"\d{4}/\d{2}/\d{2}"\[dp\]', query):
        issues.append('[dp] must look like "2020/01/01"[dp] or "2020/01/01"[dp] : "2026/08/05"[dp]')
    if re.search(r"\b(and|or|not)\b", query) and re.search(r"\b(and|or|not)[a-z]", query):
        issues.append("Boolean operators must be uppercase (AND/OR/NOT) and separated by spaces")
    return issues


def parse_dates(s):
    if not s:
        return None, None
    if ":" in s:
        a, b = [x.strip() or None for x in s.split(":", 1)]
        return a, b
    return s, None


def split_concepts(query):
    parts = re.split(r"\s+(?:AND|OR)\s+", query or "", flags=re.I)
    return [p.strip().strip('"').strip("[]") for p in parts if p.strip()]


def date_suffix(platform, date_from, date_to):
    if not (date_from or date_to):
        return ""
    if platform == "pubmed":
        return f' AND ("{date_from or "0001/01/01"}"[dp] : "{date_to or "9999/12/31"}"[dp])'
    if platform == "arxiv":
        s = (date_from or "00010101").replace("/", "")
        e = (date_to or "99991231").replace("/", "")
        return f" AND submittedDate:[{s} TO {e}]"
    if platform == "europepmc":
        return f" AND PUB_YEAR:[{(date_from or '0001')[:4]} TO {(date_to or '9999')[:4]}]"
    return ""


def build_platform_queries(platform, concepts, date_from, date_to, mesh=None):
    """Translate concepts into each platform's native query syntax."""
    mesh = mesh or {}
    if platform == "pubmed":
        variants = []
        parts = []
        for c in concepts:
            ms = mesh.get(c) or []
            parts.append("(" + " OR ".join(f'"{m}"[Mesh]' for m in ms) + ")" if ms else f'("{c}"[tiab])')
        if parts:
            variants.append(" AND ".join(parts))
        variants.append(" AND ".join(f'("{c}"[tiab])' for c in concepts))
        parts = []
        for c in concepts:
            ms = mesh.get(c) or []
            if ms:
                parts.append("(" + " OR ".join([f'"{m}"[Mesh]' for m in ms] + [f'"{c}"[tiab]']) + ")")
            else:
                parts.append(f'("{c}"[tiab])')
        variants.append(" AND ".join(parts))
        suf = date_suffix("pubmed", date_from, date_to)
        return [v + suf for v in variants]
    if platform == "arxiv":
        return [" AND ".join(f'all:"{c}"' for c in concepts) + date_suffix("arxiv", date_from, date_to)]
    if platform == "europepmc":
        return [" AND ".join(f'("{c}")' for c in concepts) + date_suffix("europepmc", date_from, date_to)]
    q = " AND ".join(f'"{c}"' for c in concepts)
    return [q]


def platform_count(platform, query, date_from, date_to):
    try:
        if platform == "pubmed":
            return search_count(query)
        if platform == "openalex":
            params = {"search": query, "per-page": 1, "mailto": "research@example.com"}
            flt = []
            if date_from:
                flt.append("from_publication_date:" + date_from.replace("/", "-"))
            if date_to:
                flt.append("to_publication_date:" + date_to.replace("/", "-"))
            if flt:
                params["filter"] = ",".join(flt)
            return json.loads(http_get_retry(OPENALEX + "?" + urllib.parse.urlencode(params)))["meta"]["count"]
        if platform == "crossref":
            params = {"query.bibliographic": query, "rows": 0, "mailto": "research@example.com"}
            flt = []
            if date_from:
                flt.append("from-pub-date:" + date_from.replace("/", "-"))
            if date_to:
                flt.append("until-pub-date:" + date_to.replace("/", "-"))
            if flt:
                params["filter"] = ",".join(flt)
            return json.loads(http_get_retry(CROSSREF + "?" + urllib.parse.urlencode(params)))["message"]["total-results"]
        if platform == "arxiv":
            p = {"search_query": query, "max_results": 1, "sortBy": "relevance", "sortOrder": "descending"}
            root = ET.fromstring(http_get_retry("https://export.arxiv.org/api/query?" + urllib.parse.urlencode(p)))
            el = root.find("{http://a9.com/-/spec/opensearch/1.1/}totalResults")
            return el.text if el is not None else "0"
        if platform == "europepmc":
            p = {"query": query, "format": "json", "pageSize": 1}
            return json.loads(http_get_retry("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(p)))["hitCount"]
        if platform == "doaj":
            d = json.loads(http_get_retry("https://doaj.org/api/search/articles/" + urllib.parse.quote(query) + "?pageSize=1"))
            return d.get("total", 0)
        if platform == "hal":
            p = {"q": query, "rows": 0}
            return json.loads(http_get_retry("https://api.archives-ouvertes.fr/search/?" + urllib.parse.urlencode(p)))["response"]["numFound"]
        if platform == "semanticscholar":
            return "N/A (rate-limited without key)"
    except Exception as exc:
        return f"error: {exc}"
    return "0"


def build_strategy(concepts, sources, date_from, date_to):
    mesh = {}
    if "pubmed" in sources:
        for c in concepts:
            mesh[c] = mesh_lookup(c, 3)
            time.sleep(0.4)
    queries = {}
    for s in sources:
        queries[s] = build_platform_queries(s, concepts, date_from, date_to, mesh)
    return {
        "topic": " | ".join(concepts),
        "dates": f"{date_from or ''}:{date_to or ''}".strip(":"),
        "sources": sources,
        "mesh": mesh,
        "queries": queries,
    }


def load_records(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_records(records, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def cmd_fetch(args):
    if not os.path.isfile(PUBMED_SCRIPT):
        sys.exit(f"pubmed-live script not found at {PUBMED_SCRIPT}")
    proc = subprocess.run(
        [sys.executable, PUBMED_SCRIPT, "search", args.query, "--max", str(args.max), "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        sys.exit(f"pubmed-live search failed: {proc.stderr.strip()}")
    records = json.loads(proc.stdout)
    save_records(records, args.out)
    print(f"Saved {len(records)} records to {args.out}")


def run_pubmed_search(query, max_results):
    last = None
    for attempt in range(3):
        proc = subprocess.run(
            [sys.executable, PUBMED_SCRIPT, "search", query, "--max", str(max_results), "--format", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if proc.returncode == 0:
            return json.loads(proc.stdout)
        last = RuntimeError(f"pubmed-live search failed for {query!r}: {proc.stderr.strip()}")
        time.sleep(2 * (attempt + 1))
    raise last


def cmd_search_all(args):
    """Run several query variants for one topic, merge by PMID, and deduplicate."""
    if args.queries_file:
        with open(args.queries_file, "r", encoding="utf-8") as f:
            queries = [line.strip() for line in f if line.strip()]
    else:
        queries = [q.strip() for q in args.queries.split("|") if q.strip()]
    if not queries:
        sys.exit("No queries provided (use --queries 'a|b|c' or --queries-file).")
    merged = {}
    for q in queries:
        recs = run_pubmed_search(q, args.max)
        print(f"  {q!r}: {len(recs)} records")
        for r in recs:
            r["query"] = q
            r["source_platform"] = "pubmed"
            merged[r["pmid"]] = r
    records = list(merged.values())
    save_records(records, args.out)
    print(f"Merged {len(queries)} queries -> {len(records)} unique records saved to {args.out}")


def cmd_strategy(args):
    """Automated strategy generation: translate concepts into every platform's native query syntax."""
    concepts = [c.strip() for c in re.split(r"[|,]", args.concepts) if c.strip()]
    if len(concepts) < 1:
        sys.exit("No concepts given (use --concepts 'radiomics|lung cancer|prognosis').")
    sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
    date_from, date_to = parse_dates(args.dates)
    strategy = build_strategy(concepts, sources, date_from, date_to)

    print(f"主题/Concepts: {' | '.join(concepts)}  日期/Dates: {args.dates or '不限'}")
    if strategy["mesh"]:
        print("MeSH descriptors found:")
        for c in concepts:
            print(f"  {c}: {', '.join(strategy['mesh'].get(c, [])) if strategy['mesh'].get(c) else '(none; will use [tiab] only)'}")
    for s in sources:
        for i, q in enumerate(strategy["queries"].get(s, []), 1):
            issues = validate_query(q)
            tag = ("  WARN: " + "; ".join(issues)) if issues else ""
            if args.test:
                time.sleep(0.4)
                print(f"[{s} #{i}] count={platform_count(s, q, date_from, date_to)}  {q}{tag}")
            else:
                print(f"[{s} #{i}]  {q}{tag}")
    if args.out and "pubmed" in strategy["queries"]:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("\n".join(strategy["queries"]["pubmed"]) + "\n")
        print(f"\nPubMed query strategy saved to {args.out} (for search-all --queries-file)")
    if args.strategy_out:
        with open(args.strategy_out, "w", encoding="utf-8") as f:
            json.dump(strategy, f, ensure_ascii=False, indent=2)
        print(f"Multi-platform strategy saved to {args.strategy_out} (for search-multi --strategy-file)")


def cmd_translate(args):
    """Translate a query into every selected platform's native syntax."""
    if args.concepts:
        concepts = [c.strip() for c in re.split(r"[|,]", args.concepts) if c.strip()]
    else:
        concepts = split_concepts(args.query)
    if not concepts:
        sys.exit("Provide --concepts or --query.")
    sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
    date_from, date_to = parse_dates(args.dates)
    strategy = build_strategy(concepts, sources, date_from, date_to)
    print(f"原始检索词/Raw: {' | '.join(concepts)}  日期/Dates: {args.dates or '不限'}")
    for s in sources:
        for i, q in enumerate(strategy["queries"].get(s, []), 1):
            extra = ""
            if args.test:
                extra = f"   count={platform_count(s, q, date_from, date_to)}"
            print(f"[{s} #{i}]{extra}\n  {q}")
    if args.strategy_out:
        with open(args.strategy_out, "w", encoding="utf-8") as f:
            json.dump(strategy, f, ensure_ascii=False, indent=2)
        print(f"\nStrategy JSON saved to {args.strategy_out}")


def cmd_author_search(args):
    """Directed search: literature by a specific author, optionally at a specific institution."""
    author = args.author.strip().strip('"')
    query = f'"{author}"[au]'
    if args.affiliation:
        aff = args.affiliation.strip().strip('"')
        query += f' AND ("{aff}"[ad])'
    if args.dates:
        if ":" in args.dates:
            start, end = [x.strip() for x in args.dates.split(":", 1)]
            query += f' AND ("{start}"[dp] : "{end}"[dp])'
        else:
            query += f' AND "{args.dates.strip()}"[dp]'
    issues = validate_query(query)
    if issues:
        print("Query warnings:", "; ".join(issues))
    time.sleep(0.4)
    total = search_count(query)
    proc = subprocess.run(
        [sys.executable, PUBMED_SCRIPT, "search", query, "--max", str(args.max), "--sort", "pub_date", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        sys.exit(f"pubmed-live search failed: {proc.stderr.strip()}")
    records = json.loads(proc.stdout)
    if args.out:
        save_records(records, args.out)
    print(f"Author query: {query}")
    print(f"Total matches: {total}; showing {len(records)} (newest first)")
    years = collections.Counter((r.get("pubDate") or "")[:4] for r in records)
    print("Year distribution:", dict(sorted(years.items())))
    for r in records:
        print(f"  [{r['pmid']}] {r.get('pubDate','')} | {(r.get('title') or '')[:90]} | {r.get('journal','')}")
    if args.out:
        print(f"Saved to {args.out}")


def cmd_template(args):
    records = load_records(args.input)
    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    header = ["pmid", "title", "journal", "pubDate", "doi", "abstract"] + fields + ["decision", "reason", "evidence"]
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for r in records:
            row = [
                r.get("pmid", ""),
                r.get("title", ""),
                r.get("journal", ""),
                r.get("pubDate", ""),
                r.get("doi", ""),
                r.get("abstract", ""),
            ]
            row += [""] * len(fields)
            row += ["", "", ""]
            writer.writerow(row)
    print(f"Template written to {args.out} ({len(records)} rows, fields: {', '.join(fields)})")


def cmd_overview(args):
    """Build the standard literature-overview table (fixed comprehensive schema)."""
    records = load_records(args.input)
    header = ["pmid", "title", "journal", "pubDate", "doi", "abstract"] + OVERVIEW_FIELDS
    rows = []
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for r in records:
            row = [
                first_str(r.get("pmid")),
                first_str(r.get("title")),
                first_str(r.get("journal")),
                first_str(r.get("pubDate")),
                first_str(r.get("doi")),
                first_str(r.get("abstract")),
            ]
            for field in OVERVIEW_FIELDS:
                row.append(first_str(r.get(AUTO_FILL[field])) if field in AUTO_FILL else "")
            writer.writerow(row)
            rows.append(row)
    if args.xlsx:
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill
            from openpyxl.utils import get_column_letter
            wb = Workbook()
            ws = wb.active
            ws.title = "Literature Overview"
            ws.append(header)
            for row in rows:
                ws.append(row)
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="2F6DB3")
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            widths = [10, 45, 22, 10, 20, 60] + [18] * len(OVERVIEW_FIELDS)
            for i, w in enumerate(widths, start=1):
                ws.column_dimensions[get_column_letter(i)].width = min(w, 45)
            wb.save(args.xlsx)
            print(f"Excel written to {args.xlsx}")
        except ImportError:
            print("openpyxl not available; only CSV written")
    print(f"Overview table written to {args.out} ({len(records)} rows)")
    print("Columns: " + ", ".join(OVERVIEW_FIELDS))
    print("The agent fills every cell from the abstract text with verbatim evidence; absent info is marked 'Not stated'.")


def cmd_download_pdf(args):
    """Batch-download legal open-access PDFs (only records with an OA PDF URL)."""
    import urllib.error as urlerror
    records = load_records(args.input)
    os.makedirs(args.dir, exist_ok=True)
    manifest = []
    n_ok = n_skip = n_fail = 0
    for r in records:
        ident = r.get("pmid") or r.get("doi") or r.get("id") or "record"
        url = r.get("oa_pdf_url") or ""
        if not url:
            n_skip += 1
            manifest.append({"id": ident, "title": r.get("title", ""), "status": "skipped_no_open_pdf", "path": "", "error": ""})
            continue
        safe = re.sub(r'[^A-Za-z0-9._-]+', "_", str(ident))[:80]
        path = os.path.join(args.dir, safe + ".pdf")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; codex-literature-analysis)"})
            with urllib.request.urlopen(req, timeout=args.timeout) as resp, open(path, "wb") as f:
                data = resp.read()
                f.write(data)
            if not data.startswith(b"%PDF"):
                os.remove(path)
                n_fail += 1
                manifest.append({"id": ident, "title": r.get("title", ""), "status": "not_pdf", "path": "", "error": "downloaded content is not a PDF"})
            else:
                n_ok += 1
                manifest.append({"id": ident, "title": r.get("title", ""), "status": "downloaded", "path": path, "error": ""})
        except (urlerror.HTTPError, urlerror.URLError, OSError, TimeoutError) as exc:
            n_fail += 1
            manifest.append({"id": ident, "title": r.get("title", ""), "status": "failed", "path": "", "error": str(exc)})
        time.sleep(0.3)
    manifest_path = os.path.join(args.dir, "download_manifest.csv")
    with open(manifest_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "title", "status", "path", "error"])
        writer.writeheader()
        writer.writerows(manifest)
    print(f"PDFs: {n_ok} downloaded, {n_skip} skipped (no OA link), {n_fail} failed")
    print(f"Manifest: {manifest_path}")


MODALITY_TERMS = ["PET/CT", "FDG-PET", "PET", "chest CT", "CT", "MRI", "T1/T2", "ultrasound",
                  "X-ray", "whole slide", "H&E", "pathology", "ctDNA", "radiomics", "endoscopy",
                  "mammography", "SPECT", "molecular imaging"]

METHOD_TERMS = ["LASSO-Cox", "LASSO", "logistic regression", "Cox proportional hazards", "Cox regression",
                "nomogram", "deep learning", "convolutional neural network", "CNN", "random forest",
                "support vector machine", "ensemble", "generative adversarial network", "GAN", "transformer",
                "machine learning", "radiomics signature", "habitat radiomics", "neural network",
                "stepwise logistic regression", "linear regression", "genomic signature"]

POP_TERMS = ["non-small cell lung cancer", "nsclc", "small cell lung cancer", "sclc", "lung cancer",
             "brain metastases", "colorectal cancer", "breast cancer", "prostate cancer", "hepatocellular carcinoma",
             "pancreatic cancer", "gastric cancer", "esophageal cancer", "head and neck cancer", "ovarian cancer",
             "renal cell carcinoma", "melanoma", "lymphoma", "leukemia", "covid-19", "pneumonia", "pulmonary fibrosis",
             "copd", "alzheimer", "parkinson", "stroke", "diabetes", "heart failure", "immunotherapy", "immune checkpoint"]


def extract_study_design(text):
    t = text.lower()
    if "systematic review" in t or "meta-analysis" in t or "meta analysis" in t:
        return "Systematic review / meta-analysis"
    if (re.search(r"randomi[sz]ed\s+(?:open-label\s+)?controlled", t) or "randomized clinical trial" in t
            or "randomised clinical trial" in t):
        return "Randomized controlled trial"
    if "clinical guideline" in t or "practice guideline" in t:
        return "Clinical guideline"
    if "case-control" in t or "case control" in t:
        return "Case-control study"
    if "cross-sectional" in t or "cross sectional" in t:
        return "Cross-sectional study"
    ppos = t.find("prospective")
    rpos = t.find("retrospective")
    if rpos != -1 and (ppos == -1 or rpos < ppos):
        design = "Retrospective cohort study"
    elif ppos != -1:
        design = "Prospective cohort study"
    elif "cohort" in t:
        design = "Cohort study"
    elif "case series" in t:
        design = "Case series"
    elif "case report" in t:
        design = "Case report"
    elif "narrative review" in t or "this review" in t or "we reviewed" in t or "review focuses" in t:
        design = "Narrative review"
    elif "proof of concept" in t or "proof-of-concept" in t:
        design = "Proof of concept"
    else:
        design = "Not stated"
    is_multi = any(k in t for k in ["multi-center", "multicenter", "multi-centre", "multicentre", "multi-institutional", "multi institutional", "from three sites", "four academic medical centers"])
    if is_multi:
        design = design + " (multi-center)" if design != "Not stated" else "Multi-center study"
    return design


def extract_sample_size(text):
    for pat in [r"total of\s*([\d,]+)",
                r"([\d,]+)\s*(?:patients?|participants?)\s+(?:were|was|underwent|received|treated|diagnosed|included|enrolled|collected|analyzed|with|who|receiving)",
                r"([\d,]+)\s*samples?\s+(?:were|was|are|collected|analyzed)",
                r"cohort of\s*([\d,]+)",
                r"n\s*=\s*([\d,]+)",
                r"N\s*=\s*([\d,]+)",
                r"included\s*([\d,]+)"]:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1).replace(",", "")
    return "Not stated"


def extract_modality(text):
    found = [m for m in MODALITY_TERMS if re.search(r"\b" + re.escape(m) + r"\b", text, re.I)]
    return ", ".join(dict.fromkeys(found)) or "Not stated"


def extract_method(text):
    found = [m for m in METHOD_TERMS if re.search(r"\b" + re.escape(m) + r"\b", text, re.I)]
    return ", ".join(dict.fromkeys(found)) or "Not stated"


def extract_population(text):
    m = re.search(r"patients?\s+(?:with|undergoing|treated with|diagnosed with|receiving)\s+([^.;]{3,80})", text, re.I)
    if m:
        return " ".join(m.group(1).split())[:100]
    t = text.lower()
    hits = [p for p in POP_TERMS if p in t]
    if hits:
        return hits[0] + (" (and others)" if len(hits) > 1 else "")
    return "Not stated"


def extract_validation(text):
    t = text.lower()
    has_ext = ("external validation" in t or "externally validated" in t or "external test" in t
               or ("external" in t and ("validat" in t or "testing set" in t)))
    has_int = "internal validation" in t or "internally validated" in t or ("internal" in t and "validat" in t)
    has_ind = "independent validation" in t or "independent test" in t or "independent external" in t or "two independent validation" in t
    has_test = "test set" in t or "testing set" in t or "test dataset" in t or "held-out" in t or "validation set" in t or "validation cohort" in t
    if has_ext and (has_int or has_ind or has_test):
        return "Internal + external validation"
    if has_ext:
        return "External validation"
    if has_ind:
        return "Independent validation"
    if has_int:
        return "Internal validation"
    if has_test:
        return "Validation split (unspecified)"
    if "validation" in t:
        return "Validation (unspecified)"
    return "Not stated"


def extract_metrics(text):
    items = []
    patterns = [
        ("AUC", r"aucs?\s*(?:of|:|=)?\s*([\d.]+)"),
        ("AUC", r"area under the (?:receiver operating characteristic |operating characteristic )?curve[^.]*?([\d.]+)"),
        ("C-index", r"c-?index\s*(?:of|:|=)?\s*([\d.]+)"),
        ("HR", r"\bhr\b\s*(?:of|:|=)?\s*([\d.]+)"),
        ("HR", r"hazard ratio[^.]*?([\d.]+)"),
        ("accuracy", r"accurac\w*\s*(?:of|:|=)?\s*([\d.]+)"),
        ("sensitivity", r"sensitivit\w*\s*(?:of|:|=)?\s*([\d.]+)"),
        ("specificity", r"specificit\w*\s*(?:of|:|=)?\s*([\d.]+)"),
    ]
    for name, pat in patterns:
        for m in re.finditer(pat, text, re.I):
            val = m.group(1)
            item = f"{name} {val}"
            if item not in items:
                items.append(item)
            if len(items) >= 6:
                break
        if len(items) >= 6:
            break
    return "; ".join(items) or "Not stated"


def extract_findings(text):
    m = re.search(r"(?:CONCLUSIONS?|INTERPRETATION|CONCLUSION|SUMMARY):\s*(.{20,500})", text, re.I | re.S)
    if m:
        return " ".join(m.group(1).split())[:320]
    sents = re.split(r"(?<=[.!?])\s+", text.strip())
    tail = " ".join(sents[-2:]).strip()
    return tail[:320] if tail else "Not stated"


def extract_limitations(text):
    m = re.search(r"[^.!?]*?(?:limitation|limited by|retrospective design|small sample|proof-of-concept|proof of concept)[^.!?]*", text, re.I)
    if m:
        return " ".join(m.group(0).split())[:200]
    return "Not stated"


def evidence_level(design, validation):
    d = (design or "").lower()
    v = (validation or "").lower()
    if "guideline" in d:
        return 1
    if "systematic review" in d or "meta-analysis" in d:
        return 2
    if "randomized" in d:
        return 3
    if "prospective" in d:
        return 4 if "external" in v else 5
    if "retrospective" in d or "cohort" in d:
        return 5 if "external" in v else 6
    if "case-control" in d or "cross-sectional" in d or "case series" in d or "case report" in d:
        return 7
    if "review" in d or "proof of concept" in d:
        return 8
    return "unclear"


def auto_evidence_snippets(text):
    snippets = []
    m = re.search(r"[^.!?]*?n\s*=\s*[\d,]+[^.!?]*", text, re.I)
    if m:
        snippets.append(" ".join(m.group(0).split())[:90])
    m = re.search(r"[^.!?]*?aucs?[^.!?]*[\d.]+[^.!?]*", text, re.I)
    if m:
        snippets.append(" ".join(m.group(0).split())[:90])
    m = re.search(r"[^.!?]*?external validation[^.!?]*", text, re.I)
    if m:
        snippets.append(" ".join(m.group(0).split())[:90])
    return " | ".join(dict.fromkeys(snippets))[:400]


EXTRACT_FIELDS = [
    "study design", "population", "sample size", "imaging modality / data", "method / model",
    "validation", "performance metrics", "main findings", "limitations", "evidence level",
]

STOPWORDS = {"the", "a", "an", "and", "or", "of", "in", "on", "for", "with", "to", "by", "from",
             "vs", "versus", "using", "based", "its", "their", "this", "that", "we", "our",
             "study", "studies", "patients", "cancer", "with", "new", "novel", "analysis"}

BROWSER_ENGINES = ["bing", "duckduckgo", "google-scholar", "cnki", "wanfang", "vip", "medjournals",
                   "pubmed-web", "ciinii", "ndl", "base", "cyberleninka", "elibrary"]
ENGINE_LANGS = {"cnki": "zh-CN", "wanfang": "zh-CN", "vip": "zh-CN", "medjournals": "zh-CN",
                "ciinii": "ja", "ndl": "ja", "base": "de", "cyberleninka": "ru", "elibrary": "ru"}


def translate_text(text, target_lang="zh-CN"):
    """Translate via the free Google Translate endpoint (no API key)."""
    if not text:
        return text
    url = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=" + target_lang
           + "&dt=t&q=" + urllib.parse.quote(text))
    try:
        data = json.loads(http_get_retry(url))
        parts = []
        for seg in (data or [])[0]:
            if seg and seg[0]:
                parts.append(seg[0])
        return "".join(parts) if parts else text
    except Exception:
        return text


def cmd_translate_query(args):
    """Standalone query translation for language-specific databases."""
    result = translate_text(args.text, args.to)
    print(f"{args.text} -> {result}")


def cmd_browser_search(args):
    """Unified browser-assisted search for platforms without public APIs."""
    mjs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_search.mjs")
    node = shutil.which("node") or r"D:\Program Files\nodejs\node.exe"
    if not os.path.isfile(node):
        sys.exit("Node.js not found; browser search requires Node 22+.")
    query = args.query
    if not args.no_translate and args.engine in ENGINE_LANGS:
        translated = translate_text(query, ENGINE_LANGS[args.engine])
        if translated != query:
            print(f"[translate] {args.engine} uses {ENGINE_LANGS[args.engine]}: {query} -> {translated}")
            query = translated
    if args.print_url:
        proc = subprocess.run(
            [node, mjs, "--engine", args.engine, "--query", query, "--print-url", "1"],
            capture_output=True, text=True, encoding="utf-8",
        )
        print(proc.stdout.strip() or proc.stderr.strip())
        return
    cmd = [node, mjs, "--engine", args.engine, "--query", query, "--max", str(args.max), "--port", str(args.port)]
    if args.url:
        cmd += ["--url", args.url]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        sys.exit("browser-search failed: " + (proc.stderr.strip() or proc.stdout.strip()))
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit("browser-search returned invalid JSON: " + proc.stdout[:500])
    if data.get("error"):
        print("browser-search:", data["error"])
        print("Fallback: open the URL manually (or in the in-app browser), then save records per references/browser-patterns.md and re-run extract.")
        return
    records = []
    for it in data.get("results", []):
        author_raw = it.get("authors") or ""
        authors = [x.strip() for x in str(author_raw).split(";") if x.strip()] if isinstance(author_raw, str) else (author_raw or [])
        snippet = it.get("snippet") or it.get("meta") or it.get("abstract") or ""
        records.append({
            "id": it.get("url") or it.get("title") or "",
            "source_platform": args.engine,
            "title": it.get("title", ""),
            "url": it.get("url", ""),
            "snippet": snippet,
            "journal": it.get("journal", ""),
            "pubDate": it.get("pubDate", ""),
            "authors": authors,
            "doi": it.get("doi", ""), "abstract": it.get("abstract", ""),
            "pmid": "", "query": args.query,
        })
    save_records(records, args.out)
    if args.xlsx:
        header = ["source", "title", "authors", "journal", "pubDate", "url", "snippet", "query"]
        rows = [[
            r.get("source_platform", ""),
            r.get("title", ""),
            "; ".join(r.get("authors") or []),
            r.get("journal", ""),
            r.get("pubDate", ""),
            r.get("url", ""),
            r.get("snippet", ""),
            r.get("query", ""),
        ] for r in records]
        write_xlsx(args.xlsx, header, rows, widths=[10, 50, 30, 24, 12, 55, 45, 30])
    total = data.get("total", "")
    if total:
        print(f"browser-search [{args.engine}]: 平台共 {total} 条,提取 {data.get('count', 0)} 条 -> {args.out}")
    else:
        print(f"browser-search [{args.engine}]: {data.get('count', 0)} results -> {args.out}")
    if data.get("needsLogin"):
        print("Note: this platform usually requires login; finish login in the opened Chrome window and re-run.")


def topic_score(topic, text):
    toks = [t for t in re.findall(r"[a-z]{3,}", (topic or "").lower()) if t not in STOPWORDS]
    if not toks:
        return None
    low = (text or "").lower()
    return sum(1 for t in toks if t in low) / len(toks)


def topic_relevance(score):
    if score is None:
        return "unclear"
    if score >= 0.7:
        return "High"
    if score >= 0.4:
        return "Medium"
    return "Low"


def cmd_extract(args):
    """One-shot auto-extraction: fill the overview fields from abstract text with rules."""
    records = load_records(args.input)
    header = ["source", "pmid", "title", "journal", "pubDate", "doi", "abstract"] + OVERVIEW_FIELDS
    rows = []
    include_kws = [k.lower() for k in (args.include or "").split("|") if k.strip()]
    exclude_kws = [k.lower() for k in (args.exclude or "").split("|") if k.strip()]
    topic = args.topic or (records[0].get("query", "") if records else "") or ""
    for r in records:
        abstract = re.sub(r"<[^>]+>", " ", first_str(r.get("abstract")))
        abstract = " ".join(abstract.split())
        full = first_str(r.get("title")) + " " + abstract
        design = extract_study_design(full)
        validation = extract_validation(full)
        level = evidence_level(design, validation)
        score = topic_score(topic, full)
        rel = topic_relevance(score)
        text_low = full.lower()
        exc_hits = [k for k in exclude_kws if k in text_low]
        inc_hits = [k for k in include_kws if k in text_low]
        if exc_hits:
            decision, reason = "exclude", f"matched exclusion criteria: {', '.join(exc_hits)}"
        elif include_kws and not inc_hits:
            decision, reason = "uncertain", "no inclusion criterion matched"
        elif inc_hits:
            decision, reason = "include", f"matched inclusion criteria: {', '.join(inc_hits)}"
        elif not abstract.strip():
            decision, reason = "uncertain", "no abstract available to screen"
        elif rel == "Low":
            decision, reason = "exclude", f"low topic relevance (score {score:.2f})"
        else:
            decision, reason = "include", f"topic relevance {rel} (score {score:.2f}); evidence level {level}"
        fields = {
            "study design": design,
            "population": extract_population(full),
            "sample size": extract_sample_size(full),
            "imaging modality / data": extract_modality(full),
            "method / model": extract_method(full),
            "validation": validation,
            "performance metrics": extract_metrics(full),
            "main findings": extract_findings(abstract),
            "limitations": extract_limitations(abstract),
            "evidence level": level,
            "citation count": r.get("citation_count", ""),
            "open access status": r.get("oa_status", ""),
            "topic relevance": rel,
            "decision": decision,
            "reason": reason,
        }
        row = [
            first_str(r.get("source_platform")) or "pubmed",
            first_str(r.get("pmid")), first_str(r.get("title")), first_str(r.get("journal")),
            first_str(r.get("pubDate")), first_str(r.get("doi")), abstract,
        ]
        for f in OVERVIEW_FIELDS:
            row.append(fields.get(f, ""))
        row[OVERVIEW_FIELDS.index("evidence") + 7] = auto_evidence_snippets(abstract)
        rows.append(row)
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    if args.xlsx:
        write_xlsx(args.xlsx, header, rows)
    print(f"Auto-extracted {len(rows)} records -> {args.out}")
    print("Heuristic extraction is a first pass; the agent reviews and refines cells, decisions, and reasons.")


def write_xlsx(path, header, rows, widths=None):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = "Literature Overview"
    ws.append(header)
    for row in rows:
        ws.append(["" if v is None else v for v in row])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2F6DB3")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    if widths is None:
        widths = [10, 45, 22, 10, 20, 60] + [18] * len(OVERVIEW_FIELDS)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = min(w, 45)
    wb.save(path)
    print(f"Excel written to {path}")


def openalex_by_dois(dois):
    """Fetch OpenAlex records (citation count, OA status, PDF) for a list of DOIs."""
    dois = sorted({d.strip().lower() for d in dois if d and d.strip()})
    out = {}
    for i in range(0, len(dois), 25):
        chunk = dois[i : i + 25]
        params = {"filter": "doi:" + "|".join(chunk), "per-page": 25, "mailto": "research@example.com"}
        url = OPENALEX + "?" + urllib.parse.urlencode(params)
        data = json.loads(http_get(url))
        for w in data.get("results", []):
            doi = (w.get("doi") or "").lower().replace("https://doi.org/", "")
            if doi:
                out[doi] = w
        time.sleep(0.2)
    return out


def openalex_abstract(inverted):
    if not inverted:
        return ""
    pos = {}
    for word, idxs in inverted.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def norm_openalex(w):
    src = (w.get("primary_location") or {}).get("source") or {}
    oa = w.get("open_access") or {}
    pdf = ((w.get("best_oa_location") or {}).get("pdf_url") or "")
    status = "open_pdf" if pdf else ("oa_available" if oa.get("oa_status") not in (None, "closed") else "no_open_pdf")
    return {
        "id": w.get("id", ""),
        "source_platform": "openalex",
        "title": w.get("title", "") or "",
        "authors": [a.get("author", {}).get("display_name", "") for a in w.get("authorships", [])],
        "journal": src.get("display_name", "") or "",
        "pubDate": w.get("publication_date") or str(w.get("publication_year", "") or ""),
        "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
        "abstract": openalex_abstract(w.get("abstract_inverted_index")),
        "citation_count": w.get("cited_by_count"),
        "oa_status": oa.get("oa_status"),
        "oa_pdf_url": pdf,
        "full_text_status": status,
        "pmid": "",
    }


def openalex_search(query, max_results, date_from, date_to, sort):
    sort_map = {"citations": "cited_by_count:desc", "date": "publication_date:desc", "relevance": "relevance_score:desc"}
    params = {
        "search": query,
        "per-page": max_results,
        "sort": sort_map.get(sort, "relevance_score:desc"),
        "mailto": "research@example.com",
    }
    filters = []
    if date_from:
        filters.append("from_publication_date:" + date_from.replace("/", "-"))
    if date_to:
        filters.append("to_publication_date:" + date_to.replace("/", "-"))
    if filters:
        params["filter"] = ",".join(filters)
    url = OPENALEX + "?" + urllib.parse.urlencode(params)
    data = json.loads(http_get_retry(url))
    return [norm_openalex(w) for w in data.get("results", [])]


def norm_crossref(m):
    date_parts = (m.get("published-print") or m.get("published-online") or m.get("published") or {}).get("date-parts", [[None]])
    full = ""
    if date_parts and date_parts[0]:
        full = "-".join(str(x) for x in date_parts[0] if x is not None)
    authors = []
    for a in m.get("author", []):
        nm = " ".join(x for x in [a.get("family", ""), a.get("given", "")] if x)
        if nm:
            authors.append(nm)
    abstract = re.sub(r"<[^>]+>", " ", m.get("abstract", "") or "")
    return {
        "id": (m.get("DOI") or "").lower(),
        "source_platform": "crossref",
        "title": (m.get("title") or [""])[0],
        "authors": authors,
        "journal": (m.get("container-title") or [""])[0],
        "pubDate": full or str((m.get("issued") or {}).get("date-parts", [[None]])[0][0] or ""),
        "doi": (m.get("DOI") or "").lower(),
        "abstract": " ".join(abstract.split()),
        "citation_count": m.get("is-referenced-by-count"),
        "oa_status": "",
        "oa_pdf_url": "",
        "full_text_status": "",
        "pmid": "",
    }


def crossref_search(query, max_results, date_from, date_to, sort):
    sort_map = {"citations": "is-referenced-by-count", "date": "published", "relevance": "relevance"}
    params = {
        "query.bibliographic": query,
        "rows": max_results,
        "sort": sort_map.get(sort, "relevance"),
        "mailto": "research@example.com",
    }
    filters = []
    if date_from:
        filters.append("from-pub-date:" + date_from.replace("/", "-"))
    if date_to:
        filters.append("until-pub-date:" + date_to.replace("/", "-"))
    if filters:
        params["filter"] = ",".join(filters)
    url = CROSSREF + "?" + urllib.parse.urlencode(params)
    data = json.loads(http_get_retry(url))
    return [norm_crossref(m) for m in data.get("message", {}).get("items", [])]


def arxiv_search(query, max_results, date_from, date_to, sort):
    q = query if (":" in query or " AND " in query.upper()) else f'all:"{query}"'
    if (date_from or date_to) and "submittedDate" not in q:
        d1 = (date_from or "00010101").replace("/", "")
        d2 = (date_to or "99991231").replace("/", "")
        q += f" AND submittedDate:[{d1} TO {d2}]"
    params = {
        "search_query": q,
        "max_results": max_results,
        "sortBy": "submittedDate" if sort == "date" else "relevance",
        "sortOrder": "descending",
    }
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    print(f"  [arxiv query] {q}")
    xml_text = http_get_retry(url)
    root = ET.fromstring(xml_text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    recs = []
    for e in root.findall("a:entry", ns):
        title = " ".join((e.findtext("a:title", default="", namespaces=ns) or "").split())
        authors = [a.findtext("a:name", default="", namespaces=ns) for a in e.findall("a:author", ns)]
        published = (e.findtext("a:published", default="", namespaces=ns) or "")[:10]
        arxiv_id = (e.findtext("a:id", default="", namespaces=ns) or "").rsplit("/", 1)[-1]
        doi = ""
        for link in e.findall("a:link", ns):
            if link.get("title") == "doi":
                doi = (link.get("href") or "").replace("https://doi.org/", "")
        recs.append({
            "id": "arxiv:" + arxiv_id,
            "source_platform": "arxiv",
            "title": title,
            "authors": authors,
            "journal": "arXiv",
            "pubDate": published or str((e.findtext("a:published", default="", namespaces=ns) or "")[:4]),
            "doi": doi.lower(),
            "arxiv_id": arxiv_id,
            "abstract": " ".join((e.findtext("a:summary", default="", namespaces=ns) or "").split()),
            "citation_count": None,
            "oa_status": "green",
            "oa_pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
            "full_text_status": "open_pdf",
            "pmid": "",
        })
    return recs


def semanticscholar_search(query, max_results, date_from, date_to, sort):
    params = {
        "query": query,
        "limit": max_results,
        "fields": "title,authors,year,abstract,venue,citationCount,externalIds,openAccessPdf,publicationDate",
    }
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params)
    print(f"  [semanticscholar query] {query} (rate-limited without API key)")
    try:
        data = json.loads(http_get_retry(url))
    except Exception as exc:
        print(f"  semanticscholar unavailable: {exc}")
        return []
    recs = []
    for p in data.get("data", []):
        ext = p.get("externalIds") or {}
        pdf = (p.get("openAccessPdf") or {}).get("url") or ""
        pubdate = p.get("publicationDate") or str(p.get("year") or "")
        year = str(pubdate)[:4]
        if date_from and year and year < date_from[:4]:
            continue
        if date_to and year and year > date_to[:4]:
            continue
        recs.append({
            "id": "s2:" + (ext.get("CorpusId") or p.get("paperId", "")),
            "source_platform": "semanticscholar",
            "title": p.get("title", ""),
            "authors": [a.get("name", "") for a in p.get("authors", [])],
            "journal": p.get("venue", ""),
            "pubDate": pubdate,
            "doi": (ext.get("DOI") or "").lower(),
            "arxiv_id": ext.get("ArXiv", ""),
            "pmid": str(ext.get("PubMed") or ""),
            "abstract": p.get("abstract", "") or "",
            "citation_count": p.get("citationCount"),
            "oa_status": "open_pdf" if pdf else "",
            "oa_pdf_url": pdf,
            "full_text_status": "open_pdf" if pdf else "no_open_pdf",
        })
    return recs


def europepmc_search(query, max_results, date_from, date_to, sort):
    q = query
    if (date_from or date_to) and "PUB_YEAR:" not in q.upper():
        q += f" AND PUB_YEAR:[{(date_from or '0001')[:4]} TO {(date_to or '9999')[:4]}]"
    params = {"query": q, "format": "json", "pageSize": max_results, "resultType": "core"}
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(params)
    print(f"  [europepmc query] {q}")
    data = json.loads(http_get_retry(url))
    recs = []
    for r in data.get("resultList", {}).get("result", []):
        pdf = ""
        for u in r.get("fullTextUrlList", {}).get("fullTextUrl", []):
            if u.get("documentStyle") == "pdf" and "Open access" in u.get("availability", ""):
                pdf = u.get("url", "")
                break
        recs.append({
            "id": "pmc:" + (r.get("pmcid") or r.get("pmid") or ""),
            "source_platform": "europepmc",
            "title": r.get("title", ""),
            "authors": [a.strip() for a in (r.get("authorString") or "").split(",") if a.strip()],
            "journal": r.get("journalTitle", ""),
            "pubDate": str(r.get("pubYear", "")),
            "doi": (r.get("doi") or "").lower(),
            "pmid": str(r.get("pmid") or ""),
            "pmcid": r.get("pmcid", ""),
            "abstract": r.get("abstractText", "") or "",
            "citation_count": None,
            "oa_status": "open_pdf" if pdf else ("oa_available" if r.get("isOpenAccess") == "Y" else ""),
            "oa_pdf_url": pdf,
            "full_text_status": "open_pdf" if pdf else ("oa_available" if r.get("isOpenAccess") == "Y" else "no_open_pdf"),
        })
    return recs


def doaj_search(query, max_results, date_from, date_to, sort):
    q = query
    url = "https://doaj.org/api/search/articles/" + urllib.parse.quote(q) + f"?pageSize={max_results}"
    print(f"  [doaj query] {q}")
    data = json.loads(http_get_retry(url))
    recs = []
    for r in data.get("results", []):
        b = r.get("bibjson", {})
        year = str(b.get("year", ""))
        if date_from and year and year < date_from[:4]:
            continue
        if date_to and year and year > date_to[:4]:
            continue
        link = ""
        if b.get("link"):
            link = b["link"][0].get("url", "")
        recs.append({
            "id": "doaj:" + r.get("id", ""),
            "source_platform": "doaj",
            "title": b.get("title", ""),
            "authors": [a.get("name", "") for a in b.get("author", [])],
            "journal": (b.get("journal") or {}).get("title", ""),
            "pubDate": year,
            "doi": (b.get("doi") or "").lower(),
            "abstract": b.get("abstract", "") or "",
            "citation_count": None,
            "oa_status": "oa_available",
            "oa_pdf_url": link,
            "full_text_status": "oa_available",
            "pmid": "",
        })
    return recs


def hal_search(query, max_results, date_from, date_to, sort):
    params = {
        "q": query,
        "rows": max_results,
        "fl": "title_s,authFullName_s,doiId_s,journalTitle_s,abstract_s,producedDate_s,fileMain_s",
    }
    if date_from or date_to:
        params["fq"] = f"producedDate_s:[{(date_from or '1900-01-01').replace('/', '-')} TO {(date_to or '9999-12-31').replace('/', '-')}]"
    url = "https://api.archives-ouvertes.fr/search/?" + urllib.parse.urlencode(params)
    print(f"  [hal query] {query}")
    data = json.loads(http_get_retry(url))
    recs = []
    for d in data.get("response", {}).get("docs", []):
        recs.append({
            "id": "hal:" + (d.get("halId_s") or d.get("docid", "")),
            "source_platform": "hal",
            "title": first_str(d.get("title_s")),
            "authors": d.get("authFullName_s", []),
            "journal": first_str(d.get("journalTitle_s")),
            "pubDate": (d.get("producedDate_s") or "")[:10],
            "doi": first_str(d.get("doiId_s")).lower(),
            "abstract": first_str(d.get("abstract_s")),
            "citation_count": None,
            "oa_status": "green",
            "oa_pdf_url": first_str(d.get("fileMain_s")),
            "full_text_status": "open_pdf" if first_str(d.get("fileMain_s")) else "no_open_pdf",
            "pmid": "",
        })
    return recs


def cmd_enrich(args):
    """Enrich PubMed records with OpenAlex citation counts, OA status, and PDF links."""
    records = load_records(args.input)
    dois = [r.get("doi") for r in records]
    oa = openalex_by_dois(dois)
    n_hit = 0
    for r in records:
        doi = (r.get("doi") or "").strip().lower()
        w = oa.get(doi)
        if not w:
            continue
        n_hit += 1
        r["citation_count"] = w.get("cited_by_count")
        r["oa_status"] = (w.get("open_access") or {}).get("oa_status")
        r["oa_pdf_url"] = ((w.get("best_oa_location") or {}).get("pdf_url") or "")
        r["openalex_title"] = w.get("title")
    save_records(records, args.out)
    print(f"Enriched {n_hit}/{len(records)} records via OpenAlex -> {args.out}")
    for r in records:
        print(f"  [{r['pmid']}] citations={r.get('citation_count', '-')} OA={r.get('oa_status', '-')} {(r.get('title') or '')[:70]}")


def cmd_search_multi(args):
    """Search multiple sources (strategy-driven or single query), merge by DOI/title, deduplicate."""
    strategy = None
    if args.strategy_file:
        with open(args.strategy_file, "r", encoding="utf-8") as f:
            strategy = json.load(f)
        sources = strategy.get("sources") or list(strategy.get("queries", {}).keys())
        date_from, date_to = parse_dates(strategy.get("dates"))
    else:
        sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
        date_from, date_to = args.date_from, args.date_to
    if strategy is None and not args.query:
        sys.exit("Provide --query or --strategy-file.")
    if not sources:
        sys.exit("No sources given (use --sources pubmed,openalex,crossref).")
    merged = {}
    for src in sources:
        queries = (strategy["queries"].get(src, []) if strategy else []) or [args.query]
        for q in queries:
            if src == "pubmed":
                recs = run_pubmed_search(q, args.max)
                for r in recs:
                    r["source_platform"] = "pubmed"
            elif src == "openalex":
                recs = openalex_search(q, args.max, date_from, date_to, args.sort)
            elif src == "crossref":
                recs = crossref_search(q, args.max, date_from, date_to, args.sort)
            elif src == "arxiv":
                recs = arxiv_search(q, args.max, date_from, date_to, args.sort)
            elif src == "semanticscholar":
                recs = semanticscholar_search(q, args.max, date_from, date_to, args.sort)
            elif src == "europepmc":
                recs = europepmc_search(q, args.max, date_from, date_to, args.sort)
            elif src == "doaj":
                recs = doaj_search(q, args.max, date_from, date_to, args.sort)
            elif src == "hal":
                recs = hal_search(q, args.max, date_from, date_to, args.sort)
            else:
                print(f"  unknown source {src!r}, skipped")
                continue
            print(f"  {src}: {len(recs)} records")
            for r in recs:
                r["query"] = q
                key = (r.get("doi") or "").lower() or r.get("id") or r.get("pmid") or (r.get("title") or "").lower()
                merged.setdefault(key, r)
    records = list(merged.values())
    if args.sort == "citations":
        records.sort(key=lambda r: (r.get("citation_count") if isinstance(r.get("citation_count"), int) else -1), reverse=True)
    elif args.sort == "date":
        records.sort(key=lambda r: r.get("pubDate", ""), reverse=True)
    save_records(records, args.out)
    print(f"Merged {len(sources)} sources -> {len(records)} unique records saved to {args.out}")


def cmd_lite(args):
    """Two-pass strategy, pass 1: compact scan table before deep extraction."""
    records = load_records(args.input)
    print("| 来源 | 标识 | 年份 | 期刊 | 引用数 | OA | 标题 |")
    print("|---|---|---|---|---|---|---|")
    for r in records:
        source = first_str(r.get("source_platform")) or "pubmed"
        ident = first_str(r.get("pmid")) or first_str(r.get("doi")) or first_str(r.get("id")) or "-"
        title = first_str(r.get("title")).replace("|", "/")
        if len(title) > 70:
            title = title[:69] + "..."
        print(f"| {source} | {ident} | {first_str(r.get('pubDate'))[:4]} | {first_str(r.get('journal'))[:22]} | {r.get('citation_count', '-')} | {first_str(r.get('oa_status')) or first_str(r.get('full_text_status')) or '-'} | {title} |")
    print(f"\n共 {len(records)} 条;确认核心文献后,用 overview 做第二遍深提取。")


def fmt_bibtex_author(name):
    # Keep PubMed's "Last FM" format as-is: compound surnames and suffixes
    # (e.g., "Shahrokh Esfahani M", "Loo BW Jr") cannot be split reliably.
    return (name or "").strip()


def bibtex_entry(r, key):
    authors = " and ".join(fmt_bibtex_author(a) for a in (r.get("authors") or []))
    fields = [
        ("author", authors),
        ("title", r.get("title", "")),
        ("journal", r.get("journal", "")),
        ("year", (r.get("pubDate") or "")[:4]),
        ("volume", r.get("volume", "")),
        ("number", r.get("issue", "")),
        ("pages", r.get("pages", "")),
        ("doi", r.get("doi", "")),
        ("pmid", r.get("pmid", "")),
    ]
    lines = [f"@article{{{key},"]
    for name, val in fields:
        if val:
            esc = str(val).replace("&", "\\&").replace("%", "\\%").replace("#", "\\#")
            lines.append(f"  {name} = {{{esc}}},")
    lines.append("}")
    return "\n".join(lines)


def cmd_export(args):
    records = load_records(args.input)
    lines = []
    for r in records:
        last = ((r.get("authors") or [""])[0].split()[0] if (r.get("authors")) else "unknown").lower()
        key = f"{last}{(r.get('pubDate') or '')[:4]}{r.get('pmid', '')}"
        if args.format == "bib":
            lines.append(bibtex_entry(r, key))
        else:
            lines.append("TY  - JOUR")
            for a in r.get("authors") or []:
                lines.append(f"AU  - {a}")
            lines.append(f"TI  - {r.get('title', '')}")
            lines.append(f"JO  - {r.get('journal', '')}")
            lines.append(f"PY  - {(r.get('pubDate') or '')[:4]}")
            if r.get("volume"):
                lines.append(f"VL  - {r['volume']}")
            if r.get("issue"):
                lines.append(f"IS  - {r['issue']}")
            if r.get("pages"):
                lines.append(f"SP  - {r['pages'].split('-')[0]}")
                if "-" in r.get("pages", ""):
                    lines.append(f"EP  - {r['pages'].split('-', 1)[1]}")
            if r.get("doi"):
                lines.append(f"DO  - {r['doi']}")
            if r.get("pmid"):
                lines.append(f"PMID- {r['pmid']}")
            lines.append("ER  -")
    text = "\n\n".join(lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"Exported {len(records)} references to {args.out}")
    else:
        print(text)


def cmd_screen(args):
    records = load_records(args.input)
    include_kws = [k.strip().lower() for k in args.include.split("|") if k.strip()] if args.include else []
    exclude_kws = [k.strip().lower() for k in args.exclude.split("|") if k.strip()] if args.exclude else []
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["pmid", "title", "decision", "matched_include", "matched_exclude", "reason"])
        for r in records:
            text = ((r.get("title", "") or "") + " " + (r.get("abstract", "") or "")).lower()
            inc = [k for k in include_kws if k in text]
            exc = [k for k in exclude_kws if k in text]
            if exc:
                decision = "exclude"
                reason = f"excluded by keyword(s): {', '.join(exc)}"
            elif inc:
                decision = "include"
                reason = f"matched keyword(s): {', '.join(inc)}"
            else:
                decision = "uncertain"
                reason = "no keyword matched; needs abstract-level review"
            writer.writerow([r.get("pmid", ""), r.get("title", ""), decision, "; ".join(inc), "; ".join(exc), reason])
    print(f"Keyword triage written to {args.out}")
    print("Note: keyword triage is only a first pass; the agent must review each abstract semantically.")


def main():
    parser = argparse.ArgumentParser(description="Literature extraction/screening pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="Fetch PubMed records via pubmed-live and save as JSON")
    p_fetch.add_argument("--query", required=True)
    p_fetch.add_argument("--max", type=int, default=10)
    p_fetch.add_argument("--out", required=True)
    p_fetch.set_defaults(func=cmd_fetch)

    p_search_all = sub.add_parser("search-all", help="Run multiple query variants for a topic, merge and dedupe")
    p_search_all.add_argument("--queries", help="pipe-separated queries, e.g. 'q1|q2|q3'")
    p_search_all.add_argument("--queries-file", help="path to a file with one query per line")
    p_search_all.add_argument("--max", type=int, default=10)
    p_search_all.add_argument("--out", required=True)
    p_search_all.set_defaults(func=cmd_search_all)

    p_template = sub.add_parser("template", help="Build an extraction/screening CSV template")
    p_template.add_argument("--in", dest="input", required=True)
    p_template.add_argument("--out", required=True)
    p_template.add_argument("--fields", default=",".join(DEFAULT_FIELDS))
    p_template.set_defaults(func=cmd_template)

    p_overview = sub.add_parser("overview", help="Build the standard literature-overview table")
    p_overview.add_argument("--in", dest="input", required=True)
    p_overview.add_argument("--out", required=True)
    p_overview.add_argument("--xlsx", help="also write a formatted Excel file")
    p_overview.set_defaults(func=cmd_overview)

    p_strategy = sub.add_parser("strategy", help="Build PubMed-syntax query variants from topic concepts")
    p_strategy.add_argument("--concepts", required=True, help="pipe- or comma-separated concepts, e.g. 'radiomics|lung cancer|prognosis'")
    p_strategy.add_argument("--dates", help="date range, e.g. '2023/01/01:2026/08/05' or single date '2023/01/01'")
    p_strategy.add_argument("--sources", default="pubmed,openalex,crossref,arxiv,semanticscholar,europepmc,doaj,hal", help="platforms to generate queries for")
    p_strategy.add_argument("--max-mesh", type=int, default=3)
    p_strategy.add_argument("--out", help="save query variants to a file (one per line) for search-all --queries-file")
    p_strategy.add_argument("--strategy-out", help="save multi-platform strategy JSON for search-multi --strategy-file")
    p_strategy.add_argument("--test", action="store_true", help="run each variant against PubMed and print hit counts")
    p_strategy.set_defaults(func=cmd_strategy)

    p_translate = sub.add_parser("translate", help="Translate a query into every selected platform's native syntax")
    p_translate.add_argument("--query", help="raw query (concepts auto-split on AND/OR)")
    p_translate.add_argument("--concepts", help="pipe- or comma-separated concepts (alternative to --query)")
    p_translate.add_argument("--dates", help="date range, e.g. '2023/01/01:2026/08/05'")
    p_translate.add_argument("--sources", default="pubmed,openalex,crossref,arxiv,semanticscholar,europepmc,doaj,hal")
    p_translate.add_argument("--strategy-out", help="save strategy JSON for search-multi --strategy-file")
    p_translate.add_argument("--test", action="store_true", help="print hit counts for each translated query")
    p_translate.set_defaults(func=cmd_translate)

    p_author = sub.add_parser("author-search", help="Directed search for a specific author, optionally at an institution")
    p_author.add_argument("--author", required=True, help="author in 'Last FM' format, e.g. 'Aerts HJWL'")
    p_author.add_argument("--affiliation", help="institution/affiliation free text, e.g. 'Harvard Medical School'")
    p_author.add_argument("--dates", help="date range, e.g. '2020/01/01:2026/08/05' or single date '2020/01/01'")
    p_author.add_argument("--max", type=int, default=10)
    p_author.add_argument("--out", help="save records as JSON for the overview pipeline")
    p_author.set_defaults(func=cmd_author_search)

    p_enrich = sub.add_parser("enrich", help="Add OpenAlex citation counts, OA status, and PDF links")
    p_enrich.add_argument("--in", dest="input", required=True)
    p_enrich.add_argument("--out", required=True)
    p_enrich.set_defaults(func=cmd_enrich)

    p_export = sub.add_parser("export", help="Export records as BibTeX or RIS")
    p_export.add_argument("--in", dest="input", required=True)
    p_export.add_argument("--format", choices=["bib", "ris"], default="bib")
    p_export.add_argument("--out", help="output file (default: print to stdout)")
    p_export.set_defaults(func=cmd_export)

    p_multi = sub.add_parser("search-multi", help="Search PubMed/OpenAlex/Crossref and merge by DOI")
    p_multi.add_argument("--query", help="single query (alternative to --strategy-file)")
    p_multi.add_argument("--strategy-file", help="run queries from a strategy JSON (generated by strategy/translate)")
    p_multi.add_argument("--sources", default="pubmed,openalex,crossref")
    p_multi.add_argument("--max", type=int, default=10)
    p_multi.add_argument("--from", dest="date_from", help="start date YYYY/MM/DD")
    p_multi.add_argument("--to", dest="date_to", help="end date YYYY/MM/DD")
    p_multi.add_argument("--sort", choices=["relevance", "citations", "date"], default="relevance")
    p_multi.add_argument("--out", required=True)
    p_multi.set_defaults(func=cmd_search_multi)

    p_lite = sub.add_parser("lite", help="Two-pass pass 1: compact scan table")
    p_lite.add_argument("--in", dest="input", required=True)
    p_lite.set_defaults(func=cmd_lite)

    p_pdf = sub.add_parser("download-pdf", help="Batch-download legal open-access PDFs")
    p_pdf.add_argument("--in", dest="input", required=True)
    p_pdf.add_argument("--dir", required=True, help="output directory for PDFs + manifest")
    p_pdf.add_argument("--timeout", type=int, default=60)
    p_pdf.set_defaults(func=cmd_download_pdf)

    p_extract = sub.add_parser("extract", help="One-shot auto-extraction of overview fields from abstracts")
    p_extract.add_argument("--in", dest="input", required=True)
    p_extract.add_argument("--out", required=True)
    p_extract.add_argument("--xlsx", help="also write a formatted Excel file")
    p_extract.add_argument("--topic", help="research topic for relevance scoring (default: query stored in results)")
    p_extract.add_argument("--include", help="pipe-separated required keywords, e.g. 'external validation|prospective'")
    p_extract.add_argument("--exclude", help="pipe-separated exclusion keywords, e.g. 'review|animal|editorial'")
    p_extract.set_defaults(func=cmd_extract)

    p_bs = sub.add_parser("browser-search", help="Unified browser search for platforms without APIs (Google Scholar, CNKI, Wanfang, VIP, Bing)")
    p_bs.add_argument("--engine", choices=BROWSER_ENGINES, default="bing")
    p_bs.add_argument("--query", required=True)
    p_bs.add_argument("--max", type=int, default=50)
    p_bs.add_argument("--port", type=int, default=0, help="Chrome CDP port (default: auto-detect 9222 / DevToolsActivePort)")
    p_bs.add_argument("--url", help="override the search URL")
    p_bs.add_argument("--print-url", action="store_true", help="only print the search URL and exit")
    p_bs.add_argument("--no-translate", action="store_true", help="disable auto-translation of the query to the engine's language")
    p_bs.add_argument("--out", default="browser_results.json")
    p_bs.add_argument("--xlsx", help="also write the results as a formatted Excel file")
    p_bs.set_defaults(func=cmd_browser_search)

    p_tq = sub.add_parser("translate-query", help="Translate a query for language-specific databases")
    p_tq.add_argument("--text", required=True)
    p_tq.add_argument("--to", default="zh-CN", help="target language code (zh-CN, ja, de, fr, ru, en)")
    p_tq.set_defaults(func=cmd_translate_query)

    p_screen = sub.add_parser("screen", help="Deterministic keyword triage (first pass only)")
    p_screen.add_argument("--in", dest="input", required=True)
    p_screen.add_argument("--out", required=True)
    p_screen.add_argument("--include", help="pipe-separated keywords, e.g. 'external validation|prospective'")
    p_screen.add_argument("--exclude", help="pipe-separated keywords, e.g. 'review|animal|editorial'")
    p_screen.set_defaults(func=cmd_screen)

    args = parser.parse_args()
    try:
        args.func(args)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"Error parsing JSON: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
