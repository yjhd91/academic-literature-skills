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
import subprocess
import sys
import time
import urllib.parse
import urllib.request

SKILLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PUBMED_SCRIPT = os.path.join(SKILLS_ROOT, "pubmed-live", "scripts", "pubmed.py")
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
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
    "topic relevance",
    "decision",
    "reason",
    "evidence",
]


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": TOOL})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


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
    proc = subprocess.run(
        [sys.executable, PUBMED_SCRIPT, "search", query, "--max", str(max_results), "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pubmed-live search failed for {query!r}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


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
            merged[r["pmid"]] = r
    records = list(merged.values())
    save_records(records, args.out)
    print(f"Merged {len(queries)} queries -> {len(records)} unique records saved to {args.out}")


def cmd_strategy(args):
    """Build PubMed-syntax query variants from topic concepts (MeSH + [tiab] + Boolean + [dp])."""
    concepts = [c.strip() for c in re.split(r"[|,]", args.concepts) if c.strip()]
    if len(concepts) < 1:
        sys.exit("No concepts given (use --concepts 'radiomics|lung cancer|prognosis').")
    mesh_by_concept = {}
    for c in concepts:
        mesh_by_concept[c] = mesh_lookup(c, args.max_mesh)
        time.sleep(0.4)
    dp = ""
    if args.dates:
        if ":" in args.dates:
            start, end = [x.strip() for x in args.dates.split(":", 1)]
            dp = f' AND ("{start}"[dp] : "{end}"[dp])'
        else:
            dp = f' AND "{args.dates.strip()}"[dp]'

    variants = []
    # Variant 1: MeSH-only (max recall via descriptor mapping)
    parts = []
    for c in concepts:
        ms = mesh_by_concept[c]
        parts.append("(" + " OR ".join(f'"{m}"[Mesh]' for m in ms) + ")" if ms else f'("{c}"[tiab])')
    if parts:
        variants.append(" AND ".join(parts) + dp)
    # Variant 2: [tiab] only (explicit terms, higher precision)
    variants.append(" AND ".join(f'("{c}"[tiab])' for c in concepts) + dp)
    # Variant 3: hybrid MeSH OR [tiab]
    parts = []
    for c in concepts:
        ms = mesh_by_concept[c]
        if ms:
            ors = [f'"{m}"[Mesh]' for m in ms] + [f'"{c}"[tiab]']
            parts.append("(" + " OR ".join(ors) + ")")
        else:
            parts.append(f'("{c}"[tiab])')
    variants.append(" AND ".join(parts) + dp)

    print("MeSH descriptors found:")
    for c in concepts:
        print(f"  {c}: {', '.join(mesh_by_concept[c]) if mesh_by_concept[c] else '(none; will use [tiab] only)'}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("\n".join(variants) + "\n")
        print(f"\nQuery strategy saved to {args.out} ({len(variants)} variants)")
    print("\nVariants:")
    for v in variants:
        issues = validate_query(v)
        tag = ("  WARN: " + "; ".join(issues)) if issues else ""
        if args.test:
            time.sleep(0.4)
            c = search_count(v)
            zero = "  <-- ZERO RESULTS, refine or drop" if c == "0" else ""
            print(f"  count={c}  {v}{zero}{tag}")
        else:
            print(f"  {v}{tag}")


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
            row += [""] * len(OVERVIEW_FIELDS)
            writer.writerow(row)
    print(f"Overview table written to {args.out} ({len(records)} rows)")
    print("Columns: " + ", ".join(OVERVIEW_FIELDS))
    print("The agent fills every cell from the abstract text with verbatim evidence; absent info is marked 'Not stated'.")


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
    p_overview.set_defaults(func=cmd_overview)

    p_strategy = sub.add_parser("strategy", help="Build PubMed-syntax query variants from topic concepts")
    p_strategy.add_argument("--concepts", required=True, help="pipe- or comma-separated concepts, e.g. 'radiomics|lung cancer|prognosis'")
    p_strategy.add_argument("--dates", help="date range, e.g. '2023/01/01:2026/08/05' or single date '2023/01/01'")
    p_strategy.add_argument("--max-mesh", type=int, default=3)
    p_strategy.add_argument("--out", help="save query variants to a file (one per line) for search-all --queries-file")
    p_strategy.add_argument("--test", action="store_true", help="run each variant against PubMed and print hit counts")
    p_strategy.set_defaults(func=cmd_strategy)

    p_author = sub.add_parser("author-search", help="Directed search for a specific author, optionally at an institution")
    p_author.add_argument("--author", required=True, help="author in 'Last FM' format, e.g. 'Aerts HJWL'")
    p_author.add_argument("--affiliation", help="institution/affiliation free text, e.g. 'Harvard Medical School'")
    p_author.add_argument("--dates", help="date range, e.g. '2020/01/01:2026/08/05' or single date '2020/01/01'")
    p_author.add_argument("--max", type=int, default=10)
    p_author.add_argument("--out", help="save records as JSON for the overview pipeline")
    p_author.set_defaults(func=cmd_author_search)

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
