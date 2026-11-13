#!/usr/bin/env python3
"""prisma: turn search + screening files into auditable PRISMA 2020 counts.

Systematic reviews die on bookkeeping: the flow diagram numbers must be
reproducible from the actual files, not retyped by hand. This command reads the
raw search output and the screening decisions, recomputes duplicates itself, and
refuses to pretend the process is complete when decisions are missing.

Inputs
------
--in FILE        one or more records JSON files (repeatable). Each file becomes
                 one "database" row unless --source-label is given.
--decisions FILE CSV/JSON with one row per screened record. Recognised columns
                 (case-insensitive): doi, pmid, title, decision, reason,
                 stage. Extra columns are ignored.
--stage NAME     which decision stage to report (default title_abstract).

Decision values are normalised: include / included / yes -> included;
exclude / excluded / no -> excluded; anything else -> uncertain.

Examples
--------
python scripts/literature.py prisma --in pubmed.json --in cnki.json \
    --decisions screen.csv --out prisma.md --json prisma.json
"""

import csv
import json
import os
import re
import sys
from collections import Counter, OrderedDict

from lit_common import (
    dedupe,
    first_str,
    load_records,
    norm_doi,
    norm_pmid,
    norm_title,
    record_key,
    shorten,
    write_csv,
)

INCLUDE_WORDS = {"include", "included", "yes", "y", "纳入", "保留", "1", "true"}
EXCLUDE_WORDS = {"exclude", "excluded", "no", "n", "排除", "剔除", "0", "false"}
UNCERTAIN_WORDS = {"uncertain", "maybe", "unsure", "不清楚", "待定", "?"}

DECISION_ALIASES = ("decision", "screen", "screening", "verdict", "status", "决定", "筛选结果")
REASON_ALIASES = ("reason", "reasons", "notes", "note", "理由", "原因")
DOI_ALIASES = ("doi",)
PMID_ALIASES = ("pmid", "pubmed_id", "pubmedid")
TITLE_ALIASES = ("title", "题名", "标题")
STAGE_ALIASES = ("stage", "phase", "阶段")


def _pick(row, aliases):
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for alias in aliases:
        if alias in lowered and str(lowered[alias]).strip():
            return str(lowered[alias]).strip()
    return ""


def normalise_decision(value):
    text = str(value or "").strip().lower()
    if not text:
        return "uncertain"
    if text in INCLUDE_WORDS:
        return "included"
    if text in EXCLUDE_WORDS:
        return "excluded"
    if text in UNCERTAIN_WORDS:
        return "uncertain"
    # Free-text decisions such as "include - external validation present"
    for word in INCLUDE_WORDS:
        if text.startswith(word + " ") or text == word:
            return "included"
    for word in EXCLUDE_WORDS:
        if text.startswith(word + " ") or text == word:
            return "excluded"
    return "uncertain"


def load_decisions(path):
    """Read a CSV or JSON decision table into normalised dicts."""
    if not path:
        return []
    if path.lower().endswith(".json"):
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            data = data.get("records") or data.get("decisions") or data.get("results") or []
        rows = [row for row in data if isinstance(row, dict)]
    else:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    decisions = []
    for row in rows:
        doi = norm_doi(_pick(row, DOI_ALIASES))
        pmid = norm_pmid(_pick(row, PMID_ALIASES))
        title = _pick(row, TITLE_ALIASES)
        decision = normalise_decision(_pick(row, DECISION_ALIASES))
        reason = _pick(row, REASON_ALIASES)
        stage = _pick(row, STAGE_ALIASES).lower().replace("-", "_").replace(" ", "_") or "title_abstract"
        if stage in ("ta", "title", "abstract", "screening"):
            stage = "title_abstract"
        if stage in ("ft", "fulltext", "full"):
            stage = "full_text"
        decisions.append({
            "key": ("doi:" + doi) if doi else (("pmid:" + pmid) if pmid else ("title:" + norm_title(title))),
            "doi": doi,
            "pmid": pmid,
            "title": title,
            "decision": decision,
            "reason": reason,
            "stage": stage,
        })
    return decisions


def normalise_reason(reason):
    text = " ".join(str(reason or "").split())
    if not text:
        return "no reason recorded"
    text = re.sub(r"^matched (?:exclusion|inclusion) criteria:\s*", "", text, flags=re.I)
    return text[:120]


def compute(records_by_source, decisions, stage="title_abstract", label=None):
    """Compute PRISMA counts. Pure function: no network, no file access."""
    per_source = OrderedDict()
    combined = []
    for name, records in records_by_source.items():
        per_source[name] = len(records)
        for record in records:
            copy = dict(record)
            copy.setdefault("source_platform", name)
            combined.append(copy)
    unique, dedupe_report = dedupe(combined)

    stage_decisions = [d for d in decisions if d.get("stage", "title_abstract") == stage]
    by_key = {}
    by_title = {}
    for decision in stage_decisions:
        if decision["key"]:
            by_key[decision["key"]] = decision
        title_key = norm_title(decision.get("title"))
        if title_key:
            by_title[title_key] = decision

    included, excluded, uncertain, undecided = [], [], [], []
    reason_counter = Counter()
    matched_decisions = set()
    for record in unique:
        key = record_key(record)
        decision = by_key.get(key)
        if decision is None:
            decision = by_title.get(norm_title(record.get("title")))
        if decision is None:
            undecided.append(record)
            continue
        matched_decisions.add(id(decision))
        if decision["decision"] == "included":
            included.append(record)
        elif decision["decision"] == "excluded":
            excluded.append(record)
            reason_counter[normalise_reason(decision["reason"])] += 1
        else:
            uncertain.append(record)

    orphan_decisions = [d for d in stage_decisions if id(d) not in matched_decisions]

    return {
        "schema": "prisma-2020",
        "label": label or "",
        "stage": stage,
        "identified": sum(per_source.values()),
        "per_source": dict(per_source),
        "duplicates_removed": dedupe_report["duplicates_removed"],
        "unkeyable_records": dedupe_report["unkeyable"],
        "screened": len(unique),
        "included": len(included),
        "excluded": len(excluded),
        "uncertain": len(uncertain),
        "undecided": len(undecided),
        "exclusion_reasons": dict(reason_counter.most_common()),
        "decisions_supplied": len(stage_decisions),
        "decisions_unmatched": len(orphan_decisions),
        "duplicate_examples": dedupe_report["merged_groups"][:10],
        "pending_title_merges": dedupe_report.get("pending_review", [])[:10],
        "review_candidates": dedupe_report.get("review_candidates", [])[:10],
        "complete": len(undecided) == 0 and len(orphan_decisions) == 0,
        "included_titles": [shorten(record.get("title"), 120) for record in included[:20]],
        "excluded_records": [
            {"pmid": first_str(record.get("pmid")), "doi": first_str(record.get("doi")),
             "title": first_str(record.get("title"))}
            for record in excluded[:5000]
        ],
    }


def markdown_report(counts):
    lines = ["# PRISMA 2020 flow counts", ""]
    if counts.get("label"):
        lines += ["Review: " + counts["label"], ""]
    lines += ["Stage reported: `" + counts["stage"] + "`", ""]
    lines += ["## Identification", "", "| Source | Records |", "|---|---|"]
    for name, n in counts["per_source"].items():
        lines.append("| " + name + " | " + str(n) + " |")
    lines.append("| **Total identified** | **" + str(counts["identified"]) + "** |")
    lines.append("| Duplicates removed | " + str(counts["duplicates_removed"]) + " |")
    lines += ["", "## Screening", "", "| Step | n |", "|---|---|"]
    lines.append("| Records screened | " + str(counts["screened"]) + " |")
    lines.append("| Records excluded | " + str(counts["excluded"]) + " |")
    if counts["exclusion_reasons"]:
        lines.append("")
        lines.append("Exclusion reasons:")
        lines.append("")
        lines.append("| Reason | n |")
        lines.append("|---|---|")
        for reason, n in counts["exclusion_reasons"].items():
            lines.append("| " + reason.replace("|", "\\|") + " | " + str(n) + " |")
    lines += ["", "## Included", "", "| Step | n |", "|---|---|"]
    lines.append("| Records included | " + str(counts["included"]) + " |")
    lines.append("| Records still uncertain | " + str(counts["uncertain"]) + " |")
    lines.append("| Records with no decision | " + str(counts["undecided"]) + " |")
    lines += ["", "## Audit", "", "| Check | Result |", "|---|---|"]
    lines.append("| Decisions supplied | " + str(counts["decisions_supplied"]) + " |")
    lines.append("| Decisions matching no record | " + str(counts["decisions_unmatched"]) + " |")
    lines.append("| Process complete | " + ("yes" if counts["complete"] else "**no**") + " |")
    lines.append("")
    if not counts["complete"]:
        lines.append("> This flow is **not** ready for a manuscript. "
                     + str(counts["undecided"]) + " record(s) have no decision and "
                     + str(counts["decisions_unmatched"]) + " decision(s) match no record.")
        lines.append("")
    lines.append("Counts are computed from the supplied files, not transcribed. "
                 "Re-run after any change to the search or screening files.")
    return "\n".join(lines) + "\n"


def text_block(counts):
    """Plain-text block that can be pasted into a protocol or response letter."""
    rows = [
        ("Records identified", counts["identified"]),
        ("Duplicates removed", counts["duplicates_removed"]),
        ("Records screened", counts["screened"]),
        ("Records excluded", counts["excluded"]),
        ("Records included", counts["included"]),
        ("Uncertain", counts["uncertain"]),
        ("No decision", counts["undecided"]),
    ]
    width = max(len(label) for label, _ in rows)
    return "\n".join(label.ljust(width) + " : " + str(value) for label, value in rows)


def run(args):
    records_by_source = OrderedDict()
    for index, path in enumerate(args.input or []):
        records = load_records(path)
        name = args.source_label[index] if (args.source_label and index < len(args.source_label)) else _source_name(path)
        if name in records_by_source:
            records_by_source[name].extend(records)
        else:
            records_by_source[name] = records
    if not records_by_source:
        print("No --in files given; counting decisions only.", file=sys.stderr)
        records_by_source["(no search file)"] = []

    decisions = load_decisions(args.decisions)
    counts = compute(records_by_source, decisions, stage=args.stage, label=args.label)

    print(text_block(counts))
    print("")
    print("Complete: " + ("yes" if counts["complete"] else "no")
          + "  (decisions supplied=" + str(counts["decisions_supplied"])
          + ", unmatched=" + str(counts["decisions_unmatched"]) + ")")
    if counts["exclusion_reasons"]:
        print("Exclusion reasons: " + ", ".join(
            reason + "=" + str(n) for reason, n in counts["exclusion_reasons"].items()))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(markdown_report(counts))
        print("Markdown -> " + args.out)
    if args.json_out:
        payload = dict(counts)
        payload["generated_by"] = "literature-analysis prisma"
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print("JSON     -> " + args.json_out)
    if args.decisions_out:
        rows = [[r["pmid"], r["doi"], r["title"]] for r in counts.get("excluded_records", [])]
        if rows:
            write_csv(args.decisions_out, ["pmid", "doi", "title"], rows)
            print("CSV      -> " + args.decisions_out)

    if args.strict and not counts["complete"]:
        print("STRICT: screening is incomplete; refusing to certify the flow.", file=sys.stderr)
        return 1
    return 0


def _source_name(path):
    base = os.path.basename(path)
    return base[:-5] if base.lower().endswith(".json") else base


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "prisma",
        help="Compute auditable PRISMA 2020 flow counts from search + screening files",
        description="Recompute identification/duplicate/screening/inclusion counts instead of retyping them.",
    )
    parser.add_argument("--in", dest="input", action="append",
                        help="records JSON file (repeat for multiple databases)")
    parser.add_argument("--source-label", action="append",
                        help="database label for the matching --in file (repeat, same order)")
    parser.add_argument("--decisions", help="CSV/JSON screening decisions")
    parser.add_argument("--stage", default="title_abstract",
                        choices=["title_abstract", "full_text"], help="decision stage to report")
    parser.add_argument("--label", help="review label written into the report header")
    parser.add_argument("--out", help="write the PRISMA Markdown report")
    parser.add_argument("--json-out", help="write the counts as JSON (for audit)")
    parser.add_argument("--decisions-out", help="write excluded records as CSV")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when records remain undecided (CI-friendly)")
    parser.set_defaults(func=run)
    return parser


if __name__ == "__main__":
    import argparse
    top = argparse.ArgumentParser(description="PRISMA 2020 counts")
    subs = top.add_subparsers(dest="command")
    add_parser(subs)
    parsed = top.parse_args(["prisma"] + sys.argv[1:])
    sys.exit(parsed.func(parsed))
