#!/usr/bin/env python3
"""verify: check that references really exist before they enter a manuscript.

A literature skill is only trustworthy if it can tell you when a citation is
wrong. This command cross-checks every reference against three independent
registries and reports one of five verdicts:

    verified    >=2 sources resolve and the title matches (>=0.90)
    partial     one source resolves, or the title only roughly matches (0.70-0.90)
    mismatch    a source resolves but the title does not match it (<0.70),
                or the publication year is off by more than one year
    not_found   nothing resolves -- treat the DOI/PMID as fabricated until proven
    no_identifier   nothing to check (no DOI, no PMID, no title)

Sources: Crossref (DOI registry), PubMed (biomedical), OpenAlex (cross-domain).
A DOI that 404s in Crossref *and* OpenAlex is strong evidence of a fabricated
identifier, which is the most common LLM citation failure.

Examples
--------
python scripts/literature.py verify --in results.json --out verify.csv --md verify.md
python scripts/literature.py verify --doi 10.1186/s12967-024-06057-y
python scripts/literature.py verify --bib references.bib --strict
"""

import json
import os
import re
import sys
import urllib.parse

from lit_common import (
    HttpError,
    first_str,
    http_json,
    load_records,
    norm_doi,
    norm_pmid,
    record_year,
    shorten,
    title_similarity,
    with_mailto,
    write_csv,
)
import lit_pubmed

CROSSREF = "https://api.crossref.org/works/"
OPENALEX = "https://api.openalex.org/works/"

#: Title similarity at or above this counts as "the same paper".
STRONG_MATCH = 0.90
#: Below this the resolved record is a different paper.
WEAK_MATCH = 0.70
#: Publication years may differ by this much (online-first vs issue year).
YEAR_TOLERANCE = 1

VERDICTS = ("verified", "partial", "mismatch", "not_found", "no_identifier")


# --------------------------------------------------------------------------- #
# source lookups: every function returns a small dict or None
# --------------------------------------------------------------------------- #

def crossref_by_doi(doi):
    try:
        payload = http_json(with_mailto(CROSSREF + urllib.parse.quote(doi, safe="/")), retries=2)
    except HttpError as exc:
        if "404" in str(exc):
            return None
        return {"error": str(exc)}
    message = payload.get("message") or {}
    return {
        "source": "crossref",
        "title": first_str(message.get("title")),
        "year": _crossref_year(message),
        "journal": first_str(message.get("container-title")),
        "doi": norm_doi(message.get("DOI")) or doi,
        "type": message.get("type", ""),
    }


def _crossref_year(message):
    for key in ("issued", "published-print", "published-online", "created"):
        parts = ((message.get(key) or {}).get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            return int(parts[0])
    return 0


def openalex_by_doi(doi):
    try:
        payload = http_json(with_mailto(OPENALEX + "doi:" + urllib.parse.quote(doi, safe="/")), retries=2)
    except HttpError as exc:
        if "404" in str(exc):
            return None
        return {"error": str(exc)}
    return {
        "source": "openalex",
        "title": first_str(payload.get("title")) or first_str(payload.get("display_name")),
        "year": payload.get("publication_year") or 0,
        "journal": first_str(((payload.get("primary_location") or {}).get("source") or {}).get("display_name")),
        "doi": norm_doi(payload.get("doi")) or doi,
        "type": payload.get("type", ""),
    }


def pubmed_lookup(doi="", pmid="", title=""):
    """Resolve a PMID directly, or a DOI/title through PubMed search."""
    try:
        if pmid:
            records = lit_pubmed.fetch([pmid], with_abstracts=False)
            if records:
                return _from_pubmed(records[0])
            return None
        term = (doi + "[DOI]") if doi else ('"' + title + '"[ti]' if title else "")
        if not term:
            return None
        total, ids = lit_pubmed.search_ids(term, 1)
        if not ids:
            return None
        records = lit_pubmed.fetch(ids[:1], with_abstracts=False)
        return _from_pubmed(records[0]) if records else None
    except Exception as exc:  # network or XML failure must not kill the batch
        return {"error": str(exc)}


def _from_pubmed(record):
    return {
        "source": "pubmed",
        "title": first_str(record.get("title")),
        "year": record_year(record),
        "journal": first_str(record.get("journal")),
        "doi": norm_doi(record.get("doi")),
        "pmid": first_str(record.get("pmid")),
        "type": "journal-article",
    }


def crossref_by_title(title, year=0):
    """Last-resort lookup for records that arrive without any identifier."""
    if not title:
        return None
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode({
        "query.bibliographic": title,
        "rows": 3,
        "select": "DOI,title,issued,container-title,type",
    })
    try:
        payload = http_json(with_mailto(url), retries=2)
    except HttpError:
        return None
    items = ((payload.get("message") or {}).get("items")) or []
    best = None
    for item in items:
        candidate = {
            "source": "crossref-title",
            "title": first_str(item.get("title")),
            "year": _crossref_year(item),
            "journal": first_str(item.get("container-title")),
            "doi": norm_doi(item.get("DOI")),
            "type": item.get("type", ""),
        }
        score = title_similarity(title, candidate["title"])
        if year and candidate["year"] and abs(candidate["year"] - int(year)) > YEAR_TOLERANCE:
            score -= 0.1
        if best is None or score > best[0]:
            best = (score, candidate)
    return best[1] if best and best[0] >= WEAK_MATCH else None


# --------------------------------------------------------------------------- #
# verdict
# --------------------------------------------------------------------------- #

def verify_record(record, lookup_titles=True):
    """Return a result dict for one record (never raises)."""
    title = first_str(record.get("title"))
    year = record_year(record)
    doi = norm_doi(record.get("doi"))
    pmid = norm_pmid(record.get("pmid"))
    result = {
        "input_title": shorten(title, 160),
        "input_year": year or "",
        "input_doi": doi,
        "input_pmid": pmid,
        "verdict": "no_identifier",
        "sources_resolved": "",
        "best_title_similarity": "",
        "source_year": "",
        "source_doi": "",
        "notes": "",
    }
    if not (doi or pmid or title):
        result["notes"] = "record has no DOI, PMID or title"
        return result

    found = []
    notes = []
    if doi:
        for lookup in (crossref_by_doi, openalex_by_doi):
            item = lookup(doi)
            if item is None:
                notes.append(item_source_name(lookup) + ":404")
            elif item.get("error"):
                notes.append(item_source_name(lookup) + ":error")
            else:
                found.append(item)
    resolved_pmid = pubmed_lookup(doi=doi, pmid=pmid)
    if resolved_pmid is None:
        notes.append("pubmed:404" if (doi or pmid) else "pubmed:no-query")
    elif resolved_pmid.get("error"):
        notes.append("pubmed:error")
    else:
        found.append(resolved_pmid)

    if not found and lookup_titles and title:
        item = crossref_by_title(title, year)
        if item:
            found.append(item)
            notes.append("resolved by title search only")

    scored = [(title_similarity(title, item.get("title", "")), item) for item in found]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best_item = (scored[0] if scored else (0.0, None))
    source_years = [item.get("year") for item in found if item.get("year")]
    source_year = max(set(source_years), key=source_years.count) if source_years else 0
    distinct_sources = len({item["source"] for item in found})

    if not found:
        result["verdict"] = "not_found"
        result["notes"] = "; ".join(notes + ["no registry returned this reference"])[:400]
        return result

    result["sources_resolved"] = ",".join(sorted({item["source"] for item in found}))
    result["best_title_similarity"] = round(best_score, 3)
    result["source_year"] = source_year or ""
    result["source_doi"] = best_item.get("doi", "")

    # A bare DOI/PMID has no title to compare: judge on how many registries
    # resolve the identifier, and say so explicitly so the result is not read as
    # a stronger claim than it is.
    if not title:
        result["verdict"] = "verified" if distinct_sources >= 2 else "partial"
        notes.append("no input title; judged on identifier resolution only")
        if distinct_sources < 2:
            notes.append("only one registry confirmed this identifier")
        result["notes"] = "; ".join(notes)[:400]
        return result

    year_bad = bool(year and source_year and abs(int(year) - int(source_year)) > YEAR_TOLERANCE)
    if best_score < WEAK_MATCH:
        result["verdict"] = "mismatch"
        notes.append("resolved record title differs from the input title")
    elif year_bad:
        result["verdict"] = "mismatch"
        notes.append("publication year differs by more than " + str(YEAR_TOLERANCE))
    elif distinct_sources >= 2 and best_score >= STRONG_MATCH:
        result["verdict"] = "verified"
    elif best_score >= WEAK_MATCH:
        result["verdict"] = "partial"
        if distinct_sources < 2:
            notes.append("only one registry confirmed this reference")
    else:
        result["verdict"] = "mismatch"
    result["notes"] = "; ".join(notes)[:400]
    return result


def item_source_name(lookup):
    return "crossref" if lookup is crossref_by_doi else "openalex"


# --------------------------------------------------------------------------- #
# input adapters
# --------------------------------------------------------------------------- #

BIB_ENTRY_RE = re.compile(r"@(\w+)\s*\{\s*([^,]+),", re.S)
BIB_FIELD_RE = re.compile(r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|[\w./:-]+)", re.S)


def parse_bibtex(path):
    """Minimal BibTeX reader: enough for doi/title/year/author/journal checks.

    Not a full BibTeX parser (no @string macros, no crossref inheritance); it
    exists so a manuscript's .bib can be verified without installing a library.
    """
    with open(path, "r", encoding="utf-8-sig") as handle:
        text = handle.read()
    records = []
    for match in BIB_ENTRY_RE.finditer(text):
        entry_type, key = match.group(1).lower(), match.group(2).strip()
        body_start = match.end()
        body_end = text.find("\n@", body_start)
        body = text[body_start:body_end if body_end != -1 else len(text)]
        fields = {}
        for field_match in BIB_FIELD_RE.finditer(body):
            name = field_match.group(1).lower()
            value = field_match.group(2).strip()
            if value.startswith("{"):
                value = value[1:-1]
            elif value.startswith('"'):
                value = value[1:-1]
            fields[name] = " ".join(value.replace("{", "").replace("}", "").split())
        if not fields.get("title"):
            continue
        records.append({
            "title": fields.get("title", ""),
            "doi": fields.get("doi", ""),
            "year": fields.get("year", ""),
            "journal": fields.get("journal", "") or fields.get("booktitle", ""),
            "authors": fields.get("author", ""),
            "bib_key": key,
            "bib_type": entry_type,
        })
    return records


def records_from_dois(dois):
    return [{"doi": doi} for doi in dois if doi.strip()]


def records_from_pmids(pmids):
    out = []
    for pmid in pmids:
        pmid = norm_pmid(pmid)
        if pmid:
            metadata = lit_pubmed.fetch([pmid], with_abstracts=False)
            out.append(metadata[0] if metadata else {"pmid": pmid})
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

CSV_HEADER = [
    "verdict", "input_doi", "input_pmid", "input_year", "best_title_similarity",
    "sources_resolved", "source_year", "source_doi", "input_title", "notes",
]


def rows_from_results(results):
    return [[
        result["verdict"], result["input_doi"], result["input_pmid"], result["input_year"],
        result["best_title_similarity"], result["sources_resolved"], result["source_year"],
        result["source_doi"], result["input_title"], result["notes"],
    ] for result in results]


def summary_counts(results):
    counts = {verdict: 0 for verdict in VERDICTS}
    for result in results:
        counts[result["verdict"]] = counts.get(result["verdict"], 0) + 1
    return counts


def markdown_report(results, source_label=""):
    counts = summary_counts(results)
    lines = []
    lines.append("# Reference verification report")
    lines.append("")
    if source_label:
        lines.append("Input: `" + source_label + "`")
        lines.append("")
    lines.append("| verdict | n | meaning |")
    lines.append("|---|---|---|")
    meanings = {
        "verified": "two or more registries resolve it and the title matches",
        "partial": "one registry resolves it, or the title only roughly matches",
        "mismatch": "a registry resolves the identifier but the metadata does not match",
        "not_found": "nothing resolves it - treat as fabricated until proven",
        "no_identifier": "nothing to check (no DOI, PMID or title)",
    }
    for verdict in VERDICTS:
        lines.append("| " + verdict + " | " + str(counts.get(verdict, 0)) + " | " + meanings[verdict] + " |")
    lines.append("")
    problems = [r for r in results if r["verdict"] in ("mismatch", "not_found", "no_identifier")]
    if problems:
        lines.append("## References requiring action")
        lines.append("")
        lines.append("| verdict | DOI | year | title | note |")
        lines.append("|---|---|---|---|---|")
        for result in problems:
            lines.append("| " + " | ".join([
                result["verdict"],
                result["input_doi"] or "-",
                str(result["input_year"] or "-"),
                _escape(result["input_title"] or "-"),
                _escape(result["notes"] or "-"),
            ]) + " |")
        lines.append("")
    lines.append("Rule: a `not_found` DOI must not be cited. Replace it with a verified")
    lines.append("reference or drop the claim it supports.")
    return "\n".join(lines) + "\n"


def _escape(value):
    return str(value).replace("|", "\\|")


def run(args):
    records = []
    if args.input:
        records.extend(load_records(args.input))
    if args.bib:
        records.extend(parse_bibtex(args.bib))
    if args.dois_file:
        with open(args.dois_file, "r", encoding="utf-8-sig") as handle:
            records.extend(records_from_dois([line.strip() for line in handle if line.strip()]))
    if args.pmids_file:
        with open(args.pmids_file, "r", encoding="utf-8-sig") as handle:
            records.extend(records_from_pmids([line.strip() for line in handle if line.strip()]))
    if args.doi:
        records.extend(records_from_dois(args.doi))
    if args.pmid:
        records.extend(records_from_pmids(args.pmid))
    if not records:
        print("Nothing to verify. Pass --in, --bib, --doi, --pmid, --dois-file or --pmids-file.",
              file=sys.stderr)
        return 2
    if args.limit:
        records = records[: args.limit]

    print("Verifying " + str(len(records)) + " reference(s) against Crossref / PubMed / OpenAlex")
    results = []
    for position, record in enumerate(records, 1):
        result = verify_record(record, lookup_titles=not args.no_title_lookup)
        results.append(result)
        print("  [" + str(position) + "/" + str(len(records)) + "] " + result["verdict"].ljust(13)
              + " " + (result["input_doi"] or result["input_pmid"] or result["input_title"])[:90])

    counts = summary_counts(results)
    print("")
    print("Summary: " + ", ".join(verdict + "=" + str(counts[verdict]) for verdict in VERDICTS if counts[verdict]))

    if args.out:
        write_csv(args.out, CSV_HEADER, rows_from_results(results))
        print("CSV  -> " + args.out)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump({"summary": counts, "results": results}, handle, ensure_ascii=False, indent=2)
        print("JSON -> " + args.json_out)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as handle:
            handle.write(markdown_report(results, args.input or args.bib or ""))
        print("MD   -> " + args.md)

    bad = counts.get("not_found", 0) + counts.get("mismatch", 0) + counts.get("no_identifier", 0)
    if args.strict and bad:
        print("STRICT: " + str(bad) + " reference(s) failed verification.", file=sys.stderr)
        return 1
    return 0


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "verify",
        help="Cross-check references against Crossref/PubMed/OpenAlex (anti-hallucination)",
        description="Verify that each reference exists and its metadata matches a real registry.",
    )
    parser.add_argument("--in", dest="input", help="records JSON produced by search-multi/search-all")
    parser.add_argument("--bib", help="BibTeX file to verify")
    parser.add_argument("--doi", action="append", help="verify one DOI (repeatable)")
    parser.add_argument("--pmid", action="append", help="verify one PMID (repeatable)")
    parser.add_argument("--dois-file", help="one DOI per line")
    parser.add_argument("--pmids-file", help="one PMID per line")
    parser.add_argument("--out", help="write a CSV verdict table")
    parser.add_argument("--json-out", help="write machine-readable verdicts")
    parser.add_argument("--md", help="write a Markdown report")
    parser.add_argument("--limit", type=int, default=0, help="verify at most N references")
    parser.add_argument("--no-title-lookup", action="store_true",
                        help="do not fall back to a Crossref title search")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when any reference fails verification (CI-friendly)")
    parser.set_defaults(func=run)
    return parser


if __name__ == "__main__":
    import argparse
    top = argparse.ArgumentParser(description="verify references")
    subs = top.add_subparsers(dest="command")
    add_parser(subs)
    parsed = top.parse_args(["verify"] + sys.argv[1:])
    sys.exit(parsed.func(parsed))
