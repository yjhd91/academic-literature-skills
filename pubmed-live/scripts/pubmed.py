#!/usr/bin/env python3
"""Real-time PubMed search and abstract retrieval via NCBI E-utilities (stdlib only).

Commands:
  search "QUERY" [--max N] [--sort relevance|pub_date] [--from YYYY/MM/DD] [--to YYYY/MM/DD] [--no-abstracts] [--format json|text]
  fetch PMID [PMID ...] [--format json|text]

Examples:
  python pubmed.py search "radiomics lung cancer prognosis" --max 10 --sort relevance
  python pubmed.py search "federated learning medical imaging" --from 2023/01/01 --to 2025/12/31 --max 20
  python pubmed.py fetch 28418006 40181378

Notes:
  - Never invent PMIDs, titles, authors, or abstracts; use only values returned here.
  - NCBI rate limit is ~3 requests/sec without an API key; the script sleeps between calls.
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "codex-pubmed-live"
REQUEST_GAP = 0.4  # seconds, keeps us under NCBI's 3 req/s limit


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": TOOL})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _pace():
    time.sleep(REQUEST_GAP)


def esearch(query, max_results, sort, date_from, date_to):
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": max_results,
        "tool": TOOL,
    }
    if sort:
        params["sort"] = sort
    if date_from or date_to:
        params["datetype"] = "edat"
        if date_from:
            params["mindate"] = date_from
        if date_to:
            params["maxdate"] = date_to
    url = EUTILS + "/esearch.fcgi?" + urllib.parse.urlencode(params)
    data = json.loads(http_get(url))
    res = data.get("esearchresult", {})
    return res.get("count", "0"), res.get("idlist", [])


MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_pubdate(value):
    """Parse PubMed pubDate like '2026 Aug 5', '2027 Apr', '2026', '2025-Oct' into (year, month)."""
    s = (value or "").strip().lower()
    if not s:
        return None
    parts = s.replace("-", " ").split()
    if not parts or not parts[0].isdigit():
        return None
    year = int(parts[0])
    month = 1
    for part in parts[1:]:
        m = MONTHS.get(part[:3])
        if m:
            month = m
            break
    return (year, month)


def parse_ym(value):
    """Parse 'YYYY/MM/DD' (user date filters) or a PubMed pubDate into (year, month)."""
    s = (value or "").strip()
    if not s:
        return None
    if "/" in s:
        parts = s.split("/")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return (int(parts[0]), int(parts[1]))
    return parse_pubdate(s)


def esummary(pmids):
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "json", "tool": TOOL}
    url = EUTILS + "/esummary.fcgi?" + urllib.parse.urlencode(params)
    data = json.loads(http_get(url))
    result = data.get("result", {})
    out = {}
    for pid in pmids:
        item = result.get(pid)
        # NCBI returns {"uid": "...", "error": "cannot get document summary"} for
        # an unknown PMID. That must NOT become a record: a blank record would
        # flow into the CSV and look like a real paper with no title.
        if not item or "error" in item:
            continue
        if not (item.get("title") or "").strip():
            continue
        doi = ""
        pmcid = ""
        for aid in item.get("articleids", []):
            if aid.get("idtype") == "doi":
                doi = aid.get("value", "")
            elif aid.get("idtype") == "pmc":
                pmcid = aid.get("value", "")
        out[pid] = {
            "pmid": pid,
            "title": item.get("title", ""),
            "authors": [a.get("name", "") for a in item.get("authors", [])],
            "journal": item.get("source", ""),
            "pubDate": item.get("pubdate", ""),
            "volume": item.get("volume", ""),
            "issue": item.get("issue", ""),
            "pages": item.get("pages", ""),
            "doi": doi,
            "pmcId": pmcid,
            "abstract": "",
        }
    return out


def efetch_abstracts(pmids):
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml", "tool": TOOL}
    url = EUTILS + "/efetch.fcgi?" + urllib.parse.urlencode(params)
    xml_text = http_get(url)
    root = ET.fromstring(xml_text)
    abstracts = {}
    for art in root.iter("PubmedArticle"):
        pmid_el = art.find("MedlineCitation/PMID")
        if pmid_el is None or not pmid_el.text:
            continue
        pmid = pmid_el.text.strip()
        abs_el = art.find("MedlineCitation/Article/Abstract")
        if abs_el is None:
            continue
        parts = []
        for at in abs_el.iter("AbstractText"):
            label = at.get("Label")
            txt = " ".join("".join(at.itertext()).split())
            parts.append(f"{label}: {txt}" if label else txt)
        abstracts[pmid] = " ".join(parts)
    return abstracts


def emit(results, fmt):
    if fmt == "text":
        for r in results:
            print(f"[{r['pmid']}] {r['pubDate']} | {r['title']}")
            if r.get("authors"):
                print("    Authors:", ", ".join(r["authors"][:6]) + (" et al." if len(r["authors"]) > 6 else ""))
            print(f"    Journal: {r['journal']}  DOI: {r['doi'] or '-'}  PMCID: {r['pmcId'] or '-'}")
            if r.get("abstract"):
                print("    Abstract:", r["abstract"][:500] + ("..." if len(r["abstract"]) > 500 else ""))
            print()
    else:
        print(json.dumps(results, ensure_ascii=False, indent=2))


def cmd_search(args):
    # Fetch extra candidates when date-filtering, then verify each record's own
    # publication date so results stay correct even if a backend ignores the
    # mindate/maxdate parameters.
    fetch_max = max(args.max * 5, 100) if (args.date_from or args.date_to) else args.max
    count, ids = esearch(args.query, fetch_max, args.sort, args.date_from, args.date_to)
    results = []
    if ids:
        meta = esummary(ids)
        _pace()
        abstracts = {} if args.no_abstracts else efetch_abstracts(ids)
        for pid in ids:
            if pid not in meta:
                continue
            meta[pid]["abstract"] = abstracts.get(pid, "")
            results.append(meta[pid])
    if args.date_from or args.date_to:
        lo = parse_ym(args.date_from)
        hi = parse_ym(args.date_to)
        kept = []
        for rec in results:
            d = parse_pubdate(rec.get("pubDate"))
            if not d:
                continue
            if lo and d < (lo[0], lo[1]):
                continue
            if hi and d > (hi[0], hi[1]):
                continue
            kept.append(rec)
        results = kept[: args.max]
    if args.format == "text":
        print(f"Total matches: {count}; showing {len(results)}")
    emit(results, args.format)


def cmd_fetch(args):
    pmids = args.pmids
    meta = esummary(pmids)
    _pace()
    abstracts = efetch_abstracts(pmids)
    results = []
    missing = []
    for pid in pmids:
        if pid not in meta:
            missing.append(pid)
            continue
        meta[pid]["abstract"] = abstracts.get(pid, "")
        results.append(meta[pid])
    if missing:
        # Never emit a placeholder for an unknown PMID: the caller must know the
        # identifier is bad rather than receive an empty record it might cite.
        print("Unknown PMID(s), no record returned: " + ", ".join(missing), file=sys.stderr)
    if not results:
        print("Error: none of the requested PMIDs exist in PubMed.", file=sys.stderr)
        sys.exit(1)
    emit(results, args.format)


def main():
    parser = argparse.ArgumentParser(description="Real-time PubMed search and abstract retrieval")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Search PubMed")
    p_search.add_argument("query")
    p_search.add_argument("--max", type=int, default=10)
    p_search.add_argument("--sort", choices=["relevance", "pub_date", "author", "journal"], default="relevance")
    p_search.add_argument("--from", dest="date_from", help="Start date YYYY/MM/DD")
    p_search.add_argument("--to", dest="date_to", help="End date YYYY/MM/DD")
    p_search.add_argument("--no-abstracts", action="store_true")
    p_search.add_argument("--format", choices=["json", "text"], default="json")
    p_search.set_defaults(func=cmd_search)

    p_fetch = sub.add_parser("fetch", help="Fetch metadata and abstracts by PMID")
    p_fetch.add_argument("pmids", nargs="+")
    p_fetch.add_argument("--format", choices=["json", "text"], default="json")
    p_fetch.set_defaults(func=cmd_fetch)

    args = parser.parse_args()
    try:
        args.func(args)
    except urllib.error.HTTPError as exc:
        print(f"NCBI API error {exc.code}: {exc.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # report cleanly for agent use
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
