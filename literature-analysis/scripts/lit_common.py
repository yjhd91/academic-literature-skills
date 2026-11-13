#!/usr/bin/env python3
"""Shared plumbing for the literature-analysis skill.

This module owns everything the individual commands must agree on:

* polite HTTP (timeout, retry with backoff, one User-Agent, optional mailto)
* identifier normalisation (DOI / PMID / title) -- the single definition used by
  search-multi, dedupe, verify and prisma, so two commands can never disagree
  about whether two records are the same paper
* record I/O (JSON list, JSON object with a records/results key, JSON Lines)
* dedupe + field merge that keeps the richest copy of a paper
* CSV / XLSX writers (XLSX degrades to a clear message instead of a traceback)

Standard library only. openpyxl is optional and only needed for --xlsx.
"""

import csv
import difflib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

__version__ = "2.0.0"

REPO_URL = "https://github.com/yjhd91/academic-literature-skills"
USER_AGENT = "academic-literature-skills/" + __version__ + " (+" + REPO_URL + ")"

#: Contact address sent to NCBI/OpenAlex/Crossref as the polite-pool `mailto`.
#: Set NCBI_EMAIL (or pass --email) to identify yourself; empty is tolerated but
#: the NCBI usage policy asks for it.
EMAIL = os.environ.get("NCBI_EMAIL", "") or os.environ.get("LIT_EMAIL", "")

#: Minimum gap between outbound requests to the same host, in seconds.
REQUEST_GAP = float(os.environ.get("LIT_REQUEST_GAP", "0.34"))

#: Optional NCBI API key (raises the E-utilities limit from 3/s to 10/s).
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")

_last_request_at = {}


class HttpError(RuntimeError):
    """Raised when a URL cannot be fetched after retries."""


#: Total seconds a single URL may spend waiting across all retries. The limit is
#: a contract, not a suggestion: when it is exhausted the caller must report the
#: source as unavailable instead of retrying forever.
RETRY_BUDGET_SECONDS = float(os.environ.get("LIT_RETRY_BUDGET", "30"))


def http_get(url, timeout=30, headers=None, retries=3, accept="text"):
    """GET a URL with polite pacing and a *bounded* retry budget.

    Returns the decoded body (``accept="json"`` returns parsed JSON).
    Raises HttpError with the last failure so callers can report *why* a source
    was skipped instead of silently returning an empty list.

    Retry rules (also documented in SKILL.md):
      * 429/5xx and transport errors are retried, up to ``retries`` attempts;
      * ``Retry-After`` is honoured when the server sends it;
      * all sleeping for one URL is capped by ``RETRY_BUDGET_SECONDS`` (30 s);
      * 4xx other than 429 is not retried - it will not get better.
    """
    host = urllib.parse.urlparse(url).netloc
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json" if accept == "json" else "*/*"}
    if headers:
        hdrs.update(headers)
    last = None
    spent = 0.0
    for attempt in range(max(1, retries)):
        gap = REQUEST_GAP - (time.time() - _last_request_at.get(host, 0))
        if gap > 0:
            time.sleep(min(gap, 2.0))
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            _last_request_at[host] = time.time()
            if accept == "json":
                return json.loads(body)
            return body
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in (429, 500, 502, 503, 504):
                break
            wait = min(2.0 * (attempt + 1), 8.0)
            retry_after = (exc.headers or {}).get("Retry-After") if hasattr(exc, "headers") else None
            if retry_after:
                try:
                    wait = min(float(retry_after), 30.0)
                except ValueError:
                    pass
            if spent + wait > RETRY_BUDGET_SECONDS:
                break
            time.sleep(wait)
            spent += wait
        except Exception as exc:  # timeout, DNS, connection reset
            last = exc
            wait = min(2.0 * (attempt + 1), 8.0)
            if spent + wait > RETRY_BUDGET_SECONDS:
                break
            time.sleep(wait)
            spent += wait
    raise HttpError("GET " + url + " failed after " + str(round(spent, 1)) + "s of retries: " + str(last))


def http_json(url, **kwargs):
    kwargs["accept"] = "json"
    return http_get(url, **kwargs)


def with_mailto(url):
    """Append the polite-pool mailto parameter when an address is configured."""
    if not EMAIL:
        return url
    sep = "&" if "?" in url else "?"
    return url + sep + urllib.parse.urlencode({"mailto": EMAIL})


DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*|https?://doi\.org/|urn:doi:)", re.I)
DOI_TRAIL_RE = re.compile(r"[\s.,;:)\]>'\"。，；]+$")
DOI_SHAPE_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def norm_doi(value):
    """Canonical form of a DOI: bare ``10.x/...``, lowercase, no URL wrapper.

    ``https://doi.org/10.1000/ABC.`` and ``doi:10.1000/abc`` both become
    ``10.1000/abc``. Unrecognisable values return ``""`` so callers can fall
    back to the next identifier instead of building a bogus dedupe key.
    """
    if not value:
        return ""
    text = urllib.parse.unquote(str(value)).strip()
    text = DOI_PREFIX_RE.sub("", text).strip()
    text = DOI_TRAIL_RE.sub("", text)
    if not DOI_SHAPE_RE.match(text.lower()):
        return ""
    return text.lower()


def is_valid_doi(value):
    return bool(norm_doi(value))


PMID_RE = re.compile(r"^\d{1,9}$")


def norm_pmid(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    text = str(value).strip()
    if not PMID_RE.match(text):
        m = re.search(r"(?:pmid[:\s]*)(\d{1,9})", text, re.I)
        return m.group(1) if m else ""
    return text


_NON_WORD = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")


def norm_title(value):
    """Lowercase, accent-folded, punctuation-free title used for similarity.

    Returns "" for empty input so callers never treat two empty titles as equal.
    """
    if not value:
        return ""
    if isinstance(value, (list, tuple)):
        value = " ".join(str(v) for v in value)
    text = unicodedata.normalize("NFKC", str(value)).lower()
    text = strip_markup(text)
    text = _NON_WORD.sub(" ", text)
    return " ".join(text.split())


_TAG_RE = re.compile(r"<[^>]+>")


def strip_markup(value):
    """Remove HTML/JATS tags and collapse whitespace (abstracts arrive as HTML)."""
    if not value:
        return ""
    text = str(value)
    if "<" in text and ">" in text:
        text = _TAG_RE.sub(" ", text)
    try:
        import html
        text = html.unescape(text)
    except Exception:
        pass
    return " ".join(text.split())


def first_str(value):
    """First element of a list, or the scalar; empty string for None/empty."""
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    if value is None:
        return ""
    return str(value)


def record_year(record):
    """Best-effort four-digit publication year from the common field names."""
    for key in ("year", "publication_year", "pubDate", "published", "issued"):
        raw = record.get(key)
        if isinstance(raw, dict):
            raw = first_str(raw.get("date-parts"))
        text = first_str(raw) if not isinstance(raw, str) else raw
        m = re.search(r"(19|20)\d{2}", text or "")
        if m:
            return int(m.group(0))
    return 0


def record_key(record):
    """Strong identity for dedupe, in decreasing order of trust.

    DOI > PMID > provider id. The old code used the raw DOI string, so
    ``10.1/ABC`` and ``https://doi.org/10.1/abc`` were counted as two papers;
    this function is the fix.

    Titles are deliberately *not* part of the strong key: two records with the
    same title and different DOIs may be a preprint and its published version,
    or two different studies with a generic title. Only a missing identifier
    falls back to title matching, and that path is flagged for human review.
    """
    doi = norm_doi(record.get("doi"))
    if doi:
        return "doi:" + doi
    pmid = norm_pmid(record.get("pmid"))
    if pmid:
        return "pmid:" + pmid
    for key in ("openalex_id", "id", "s2_id", "arxiv_id"):
        value = first_str(record.get(key)).strip()
        if value and not value.startswith("http"):
            return "id:" + value.lower()
    return ""


#: A title shorter than this is too generic to match on ("Editorial", "Reply").
#: CJK characters carry about twice the information of a Latin letter, so they
#: are counted twice: a 16-character Chinese title is a full title, not a stub.
MIN_TITLE_KEY_LEN = 24


def _title_weight(text):
    cjk = sum(1 for ch in text if "\u3400" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff")
    return len(text) + cjk


def title_key(record):
    title = norm_title(record.get("title"))
    return title if _title_weight(title) >= MIN_TITLE_KEY_LEN else ""


MERGE_PREFER_LONGER = ("abstract", "title")
MERGE_MAX = ("citation_count", "cited_by_count")


def merge_records(base, incoming):
    """Fold ``incoming`` into ``base`` without losing information from either.

    Empty fields are filled, abstracts keep the longer copy, citation counts keep
    the maximum, and ``sources`` records every platform that returned the paper.
    Mutates and returns ``base``.
    """
    for key, value in incoming.items():
        if key in ("sources", "dedupe_basis"):
            continue
        if key in MERGE_MAX:
            try:
                if value is not None and float(value) > float(base.get(key) or -1):
                    base[key] = value
            except (TypeError, ValueError):
                base.setdefault(key, value)
            continue
        current = base.get(key)
        if current in (None, "", [], {}):
            if value not in (None, "", [], {}):
                base[key] = value
            continue
        if key in MERGE_PREFER_LONGER and isinstance(value, str) and len(value) > len(str(current)):
            base[key] = value
    merged_sources = list(base.get("sources") or [])
    for source in _incoming_sources(base) + _incoming_sources(incoming):
        if source and source not in merged_sources:
            merged_sources.append(source)
    if merged_sources:
        base["sources"] = merged_sources
    return base


def _incoming_sources(record):
    sources = record.get("sources")
    if isinstance(sources, (list, tuple)):
        return [str(s) for s in sources if s]
    platform = record.get("source_platform") or record.get("source")
    return [str(platform)] if platform else []


def dedupe(records):
    """Collapse duplicates and return ``(unique_records, report)``.

    Three rules, in order:

    1. Same DOI/PMID/provider id -> one record, merged, ``basis=identifier``.
    2. No identifier on one side -> attach by identical normalised title, but
       mark the record ``dedupe_basis=title`` and list it under
       ``pending_review``. Chinese databases often return no DOI, so this is
       common; it is merged to avoid double counting, never silently.
    3. Two *different* identifiers with the same title (preprint vs published
       version, or a generic title) -> **not** merged. They are reported under
       ``review_candidates`` so a human decides.

    Nothing is dropped silently: the report accounts for every input record.
    """
    records = list(records or [])
    unique = []
    strong_index = {}
    report = {
        "input": len(records),
        "unique": 0,
        "duplicates_removed": 0,
        "merged_by_identifier": 0,
        "merged_by_title_pending_review": 0,
        "merged_fields": {},
        "merged_groups": [],
        "pending_review": [],
        "review_candidates": [],
        "unkeyable": 0,
    }

    def _merge_into(target, record, basis):
        before = dict(target)
        merge_records(target, record)
        for field, value in target.items():
            if before.get(field) in (None, "", [], {}) and value not in (None, "", [], {}):
                report["merged_fields"][field] = report["merged_fields"].get(field, 0) + 1
        if basis == "identifier":
            report["merged_by_identifier"] += 1
        else:
            report["merged_by_title_pending_review"] += 1
            target["dedupe_basis"] = "title"
            report["pending_review"].append({
                "kept": target.get("doi") or target.get("pmid") or shorten(target.get("title"), 90),
                "folded": record.get("doi") or record.get("pmid") or shorten(record.get("title"), 90),
                "reason": "matched on title only (no identifier)",
            })

    # Pass 1: strong identifiers.
    title_waiting = []
    for record in records:
        key = record_key(record)
        if not key:
            title_waiting.append(record)
            continue
        if key in strong_index:
            _merge_into(unique[strong_index[key]], record, "identifier")
        else:
            strong_index[key] = len(unique)
            unique.append(dict(record))

    # Pass 2: identifier-less records, matched on an exact normalised title.
    title_index = {}
    for position, record in enumerate(unique):
        key = title_key(record)
        if key and key not in title_index:
            title_index[key] = position
    for record in title_waiting:
        key = title_key(record)
        if key and key in title_index:
            _merge_into(unique[title_index[key]], record, "title")
            continue
        position = len(unique)
        unique.append(dict(record))
        if key:
            title_index[key] = position
        report["unkeyable"] += 1

    # Pass 3: different identifiers sharing one title are reported, never merged.
    seen_titles = {}
    for position, record in enumerate(unique):
        if record.get("dedupe_basis") == "title":
            continue
        key = title_key(record)
        if not key:
            continue
        if key in seen_titles:
            other = unique[seen_titles[key]]
            if record_key(other) and record_key(record) and record_key(other) != record_key(record):
                report["review_candidates"].append({
                    "title": shorten(record.get("title"), 120),
                    "key_a": record_key(other),
                    "key_b": record_key(record),
                    "note": "same title, different identifiers - check whether these are the "
                            "same study (preprint/published) before merging",
                })
        else:
            seen_titles[key] = position

    report["unique"] = len(unique)
    report["duplicates_removed"] = report["merged_by_identifier"] + report["merged_by_title_pending_review"]
    # Invariant: every input record is either kept unique or folded into one.
    assert report["input"] == report["unique"] + report["duplicates_removed"], report
    return unique, report


def load_records(path):
    """Read records from a JSON list, a JSON object, or JSON Lines.

    Accepts the shapes produced by every command in this repository plus the
    common wrappers other tools emit (``{"records": [...]}``,
    ``{"results": [...]}``, ``{"data": [...]}``) so files can be concatenated.
    """
    with open(path, "r", encoding="utf-8-sig") as handle:
        text = handle.read().strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        lines = [line for line in text.splitlines() if line.strip()]
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                raise SystemExit("Cannot parse " + path + " as JSON or JSON Lines.")
        return records
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("records", "results", "data", "items", "works"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    raise SystemExit("Unsupported JSON shape in " + path)


def save_records(records, path):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
    return len(records)


def write_csv(path, header, rows):
    """UTF-8 BOM CSV so Excel on Windows opens Chinese correctly."""
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def openpyxl_available():
    try:
        import openpyxl  # noqa: F401
        return True
    except Exception:
        return False


def write_xlsx(path, header, rows, title="Sheet1", widths=None, note=""):
    """Formatted XLSX. Returns True on success, False when openpyxl is absent.

    Never raises ImportError at the user: the caller already wrote CSV and only
    needs to print the returned installer hint.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
    except Exception:
        print("! openpyxl is not installed, so " + str(path) + " was skipped.")
        print("  Install it with:  python -m pip install openpyxl")
        if note:
            print("  " + note)
        return False
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title[:31] or "Sheet1"
    sheet.append(list(header))
    for row in rows:
        sheet.append(["" if value is None else value for value in row])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2F6DB3")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    if widths is None:
        widths = [18] * len(header)
    for i, width in enumerate(widths, start=1):
        if i > len(header):
            break
        sheet.column_dimensions[get_column_letter(i)].width = max(8, min(int(width or 18), 60))
    workbook.save(path)
    return True


def title_similarity(left, right):
    """0..1 similarity between two titles after normalisation."""
    a, b = norm_title(left), norm_title(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def shorten(value, limit=80):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def print_table(header, rows, limit=None):
    """Plain aligned table for humans and for log capture."""
    rows = list(rows)
    if limit is not None:
        rows = rows[:limit]
    widths = [len(str(h)) for h in header]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(cell)))
    line = "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(header))
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)))


def script_dir():
    return os.path.dirname(os.path.abspath(__file__))


def main_cli_guard(func):
    """Uniform error handling for command entry points."""
    try:
        return func()
    except HttpError as exc:
        print("Network error: " + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    # Tiny self-check: `python lit_common.py` proves the module imports and that
    # identifier normalisation behaves, without touching the network.
    assert norm_doi("https://doi.org/10.1186/S12967-024-06057-Y.") == "10.1186/s12967-024-06057-y"
    assert norm_doi("doi: 10.1186/s12967-024-06057-y") == "10.1186/s12967-024-06057-y"
    assert norm_doi("not a doi") == ""
    assert norm_pmid("PMID: 40181378") == "40181378"
    assert norm_title("Radiomics — in Lung Cancer!") == "radiomics in lung cancer"
    assert title_similarity("Radiomics in lung cancer", "Radiomics in lung cancer.") == 1.0

    # Same identifier in two spellings: one record, merged, counted.
    records, report = dedupe([
        {"doi": "10.1186/S12967-024-06057-Y", "title": "A real title about radiomics in lung cancer",
         "abstract": "short", "source_platform": "crossref"},
        {"doi": "https://doi.org/10.1186/s12967-024-06057-y.",
         "title": "A real title about radiomics in lung cancer", "abstract": "a much longer abstract",
         "citation_count": 12, "source_platform": "openalex"},
    ])
    assert len(records) == 1, records
    assert report["merged_by_identifier"] == 1
    assert records[0]["abstract"] == "a much longer abstract"
    assert records[0]["citation_count"] == 12
    assert sorted(records[0]["sources"]) == ["crossref", "openalex"]

    # No identifier: matched on a long identical title, but flagged for review.
    records, report = dedupe([
        {"title": "Deep learning for lung cancer prognosis in a multicentre cohort"},
        {"title": "Deep learning for lung cancer prognosis in a multicentre cohort."},
    ])
    assert len(records) == 1 and report["merged_by_title_pending_review"] == 1
    assert report["pending_review"], "title-only merge must stay visible"

    # Different identifiers, same title: NOT merged, reported instead.
    records, report = dedupe([
        {"doi": "10.1186/s12967-024-06057-y", "title": "Same title in both records here"},
        {"doi": "10.1000/182", "title": "Same title in both records here"},
    ])
    assert len(records) == 2, records
    assert len(report["review_candidates"]) == 1
    print("lit_common " + __version__ + " self-check OK")
