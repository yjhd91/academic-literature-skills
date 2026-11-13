#!/usr/bin/env python3
"""Built-in PubMed client (NCBI E-utilities), standard library only.

Why this file exists: ``literature.py`` used to shell out to
``../pubmed-live/scripts/pubmed.py``. That made the literature-analysis skill
fail for anyone who installed it without its sibling skill, and it hid the real
error behind a subprocess exit code. This module is the single in-skill client,
so both skills can be installed independently.

It deliberately returns the same record shape as pubmed-live so existing
pipelines and saved JSON files keep working:

    pmid, title, authors, journal, pubDate, volume, issue, pages, doi, pmcId,
    abstract

Environment:
    NCBI_EMAIL    contact address (NCBI usage policy asks for it)
    NCBI_API_KEY  optional key, raises the limit from 3 req/s to 10 req/s
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from lit_common import EMAIL, NCBI_API_KEY, HttpError, http_get, strip_markup

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "academic-literature-skills"
#: 0.34 s keeps a keyless client just under NCBI's 3 requests/second ceiling.
REQUEST_GAP = 0.12 if NCBI_API_KEY else 0.34

_last_call = [0.0]


def _params(extra):
    params = dict(extra)
    params["tool"] = TOOL
    if EMAIL:
        params["email"] = EMAIL
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    return params


def _get(endpoint, params, retries=3):
    """E-utilities GET with pacing and retry; raises HttpError with context."""
    url = EUTILS + "/" + endpoint + "?" + urllib.parse.urlencode(_params(params))
    last = None
    for attempt in range(retries):
        gap = REQUEST_GAP - (time.time() - _last_call[0])
        if gap > 0:
            time.sleep(gap)
        try:
            body = http_get(url, timeout=40, retries=1)
            _last_call[0] = time.time()
            return body
        except HttpError as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise HttpError("NCBI " + endpoint + " failed: " + str(last))


def search_ids(query, max_results=10, sort="relevance", date_from=None, date_to=None):
    """Return ``(total_count, [pmid, ...])`` for a PubMed query."""
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": max(0, int(max_results)),
    }
    if sort:
        params["sort"] = sort
    if date_from or date_to:
        params["datetype"] = "pdat"
        if date_from:
            params["mindate"] = _ymd(date_from)
        if date_to:
            params["maxdate"] = _ymd(date_to)
    payload = json.loads(_get("esearch.fcgi", params))
    result = payload.get("esearchresult", {})
    return str(result.get("count", "0")), list(result.get("idlist", []))


def _ymd(value):
    """Normalise 2023/1/5 or 2023-01-05 to the YYYY/MM/DD NCBI expects."""
    parts = re.split(r"[-/.]", str(value).strip())
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return "%04d/%02d/%02d" % (int(parts[0]), int(parts[1]), int(parts[2]))
    if len(parts) == 1 and parts[0].isdigit() and len(parts[0]) == 8:
        return parts[0][:4] + "/" + parts[0][4:6] + "/" + parts[0][6:]
    return str(value).strip()


def summaries(pmids):
    """esummary metadata keyed by PMID, in the pubmed-live record shape."""
    if not pmids:
        return {}
    payload = json.loads(_get("esummary.fcgi", {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "json",
    }))
    result = payload.get("result", {})
    out = {}
    for pmid in pmids:
        item = result.get(pmid)
        # NCBI answers an unknown PMID with {"error": "cannot get document
        # summary"}. Skipping it keeps fabricated PMIDs out of every downstream
        # table instead of producing an empty record that looks real.
        if not isinstance(item, dict) or "error" in item:
            continue
        if not strip_markup(item.get("title", "")).strip():
            continue
        doi, pmcid = "", ""
        for article_id in item.get("articleids", []) or []:
            if article_id.get("idtype") == "doi":
                doi = article_id.get("value", "")
            elif article_id.get("idtype") == "pmc":
                pmcid = article_id.get("value", "")
        out[pmid] = {
            "pmid": pmid,
            "title": strip_markup(item.get("title", "")),
            "authors": [a.get("name", "") for a in item.get("authors", []) or []],
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


def abstracts(pmids):
    """Full abstracts keyed by PMID, with section labels preserved."""
    if not pmids:
        return {}
    xml_text = _get("efetch.fcgi", {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"})
    root = ET.fromstring(xml_text)
    out = {}
    for article in root.iter("PubmedArticle"):
        pmid_el = article.find("MedlineCitation/PMID")
        if pmid_el is None or not pmid_el.text:
            continue
        pmid = pmid_el.text.strip()
        abstract_el = article.find("MedlineCitation/Article/Abstract")
        if abstract_el is None:
            continue
        parts = []
        for node in abstract_el.iter("AbstractText"):
            label = node.get("Label")
            text = " ".join("".join(node.itertext()).split())
            parts.append((label + ": " + text) if label else text)
        out[pmid] = " ".join(parts)
    return out


def search(query, max_results=10, sort="relevance", date_from=None, date_to=None,
           with_abstracts=True, date_filter_retry=True):
    """Search PubMed and return records in the published pubmed-live shape.

    ``date_filter_retry`` re-checks each record's own publication date, because
    PubMed's ``pdat`` filter also matches the electronic date of ahead-of-print
    records and can return items outside the requested window.
    """
    fetch_max = max(max_results * 5, 100) if (date_from or date_to) else max_results
    if date_filter_retry:
        _, ids = search_ids(query, fetch_max, sort, date_from, date_to)
    else:
        _, ids = search_ids(query, max_results, sort, None, None)
    records = fetch(ids, with_abstracts=with_abstracts) if ids else []
    if date_filter_retry and (date_from or date_to):
        low = _year_month(date_from)
        high = _year_month(date_to)
        kept = []
        for record in records:
            stamp = _pubdate_year_month(record.get("pubDate"))
            if not stamp:
                continue
            if low and stamp < low:
                continue
            if high and stamp > high:
                continue
            kept.append(record)
        records = kept[:max_results]
    else:
        records = records[:max_results]
    return records


def count(query):
    total, _ = search_ids(query, 0)
    return int(total) if str(total).isdigit() else 0


def fetch(pmids, with_abstracts=True):
    """Fetch metadata (+abstracts) for explicit PMIDs, preserving input order."""
    pmids = [p for p in pmids if p]
    if not pmids:
        return []
    meta = summaries(pmids)
    body = abstracts(pmids) if with_abstracts else {}
    records = []
    for pmid in pmids:
        if pmid not in meta:
            continue
        meta[pmid]["abstract"] = body.get(pmid, "")
        records.append(meta[pmid])
    return records


MONTHS = {name: i + 1 for i, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _pubdate_year_month(value):
    """'2026 Aug 5' / '2027 Apr' / '2026' / '2025-Oct' -> (year, month)."""
    text = (value or "").strip().lower()
    if not text:
        return None
    parts = text.replace("-", " ").split()
    if not parts or not parts[0].isdigit():
        return None
    year = int(parts[0])
    month = 1
    for part in parts[1:]:
        found = MONTHS.get(part[:3])
        if found:
            month = found
            break
    return (year, month)


def _year_month(value):
    """'YYYY/MM/DD' -> (year, month) so date windows compare as tuples."""
    if not value:
        return None
    parts = re.split(r"[-/.]", str(value).strip())
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return (int(parts[0]), int(parts[1]))
    return _pubdate_year_month(value)


def available():
    """Health probe used by `doctor`: can we reach E-utilities at all?"""
    try:
        total, _ = search_ids("pubmed[sb]", 1)
        return True, "esearch ok (count=" + str(total) + ")"
    except Exception as exc:
        return False, str(exc)


if __name__ == "__main__":
    # `python lit_pubmed.py "query"` gives a quick manual smoke test.
    query = " ".join(sys.argv[1:]) or "radiomics lung cancer prognosis"
    for record in search(query, 2):
        print("[" + record["pmid"] + "] " + record["pubDate"] + " | " + record["title"][:90])
