"""Offline tests for PRISMA counting (lit_prisma.py)."""

import csv
import json
import os
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "literature-analysis", "scripts")
sys.path.insert(0, SCRIPTS)

import lit_prisma  # noqa: E402


def make_records(n, prefix="paper", doi=True):
    out = []
    for i in range(n):
        record = {"title": prefix + " title number " + str(i) + " with enough words"}
        if doi:
            record["doi"] = "10.1186/test-" + str(i)
        out.append(record)
    return out


def decision(record, value, reason="", stage="title_abstract"):
    return {
        "key": ("doi:" + record["doi"]) if record.get("doi") else "",
        "doi": record.get("doi", ""),
        "pmid": "",
        "title": record.get("title", ""),
        "decision": value,
        "reason": reason,
        "stage": stage,
    }


class TestDecisionParsing(unittest.TestCase):
    def test_normalise_decision_values(self):
        cases = {
            "include": "included", "INCLUDED": "included", "yes": "included", "纳入": "included",
            "exclude": "excluded", "no": "excluded", "排除": "excluded",
            "uncertain": "uncertain", "maybe": "uncertain", "": "uncertain", "???": "uncertain",
            "include - external validation present": "included",
        }
        for raw, expected in cases.items():
            self.assertEqual(lit_prisma.normalise_decision(raw), expected, raw)

    def test_load_decisions_csv(self):
        handle, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(handle, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["PMID", "DOI", "Title", "Decision", "Reason"])
            writer.writerow(["", "10.1186/test-1", "A title", "Exclude", "review article"])
        self.addCleanup(os.unlink, path)
        rows = lit_prisma.load_decisions(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["key"], "doi:10.1186/test-1")
        self.assertEqual(rows[0]["decision"], "excluded")
        self.assertEqual(rows[0]["reason"], "review article")

    def test_stage_alias_normalisation(self):
        handle, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(handle, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["doi", "decision", "stage"])
            writer.writerow(["10.1186/test-1", "include", "FT"])
        self.addCleanup(os.unlink, path)
        self.assertEqual(lit_prisma.load_decisions(path)[0]["stage"], "full_text")


class TestCompute(unittest.TestCase):
    def test_counts_and_completeness(self):
        pubmed = make_records(4, "pubmed")
        cnki = make_records(3, "cnki", doi=False)
        # One record appears in both databases, by identifier.
        pubmed.append({"doi": "10.1186/test-0", "title": "pubmed title number 0 with enough words"})
        decisions = [decision(r, "included") for r in pubmed[:2]]
        decisions += [decision(r, "excluded", "not a primary study") for r in pubmed[2:4]]
        counts = lit_prisma.compute({"pubmed": pubmed, "cnki": cnki}, decisions)
        self.assertEqual(counts["identified"], 8)
        self.assertEqual(counts["duplicates_removed"], 1)
        self.assertEqual(counts["screened"], 7)
        self.assertEqual(counts["included"], 2)
        self.assertEqual(counts["excluded"], 2)
        self.assertEqual(counts["undecided"], 3)
        self.assertFalse(counts["complete"])

    def test_complete_when_every_record_decided(self):
        records = make_records(2)
        decisions = [decision(r, "included") for r in records]
        counts = lit_prisma.compute({"db": records}, decisions)
        self.assertTrue(counts["complete"])
        self.assertEqual(counts["included"], 2)

    def test_exclusion_reasons_are_counted(self):
        records = make_records(3)
        decisions = [decision(records[0], "excluded", "review"),
                     decision(records[1], "excluded", "review"),
                     decision(records[2], "excluded", "animal study")]
        counts = lit_prisma.compute({"db": records}, decisions)
        self.assertEqual(counts["exclusion_reasons"]["review"], 2)
        self.assertEqual(counts["exclusion_reasons"]["animal study"], 1)

    def test_decision_matching_by_title_when_no_identifier(self):
        records = [{"title": "Recursive decision matching by normalized title works"}]
        decisions = [{"key": "", "doi": "", "pmid": "",
                      "title": "recursive decision matching by normalized title works",
                      "decision": "included", "reason": "", "stage": "title_abstract"}]
        counts = lit_prisma.compute({"db": records}, decisions)
        self.assertEqual(counts["included"], 1)

    def test_orphan_decisions_are_reported(self):
        records = make_records(1)
        decisions = [decision(records[0], "included"),
                     decision({"doi": "10.1186/not-in-set", "title": "x"}, "included")]
        counts = lit_prisma.compute({"db": records}, decisions)
        self.assertEqual(counts["decisions_unmatched"], 1)
        self.assertFalse(counts["complete"])

    def test_stage_filter(self):
        records = make_records(2)
        decisions = [decision(records[0], "included"),
                     decision(records[1], "excluded", "full text problem", stage="full_text")]
        ta = lit_prisma.compute({"db": records}, decisions, stage="title_abstract")
        ft = lit_prisma.compute({"db": records}, decisions, stage="full_text")
        self.assertEqual(ta["included"], 1)
        self.assertEqual(ta["undecided"], 1)
        self.assertEqual(ft["excluded"], 1)

    def test_report_renders_without_error(self):
        counts = lit_prisma.compute({"db": make_records(2)},
                                    [decision(make_records(2)[0], "excluded", "review")])
        text = lit_prisma.markdown_report(counts)
        self.assertIn("PRISMA 2020", text)
        self.assertIn("Duplicates removed", text)
        self.assertIn("not** ready", text) if not counts["complete"] else None

    def test_json_serialisable(self):
        counts = lit_prisma.compute({"db": make_records(2)}, [])
        json.dumps(counts, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
