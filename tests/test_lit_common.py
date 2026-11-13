"""Offline tests for the shared plumbing in lit_common.py.

Every test here must run without network access: CI has no credentials and no
guarantee that PubMed/Crossref are reachable.
"""

import json
import os
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "literature-analysis", "scripts")
sys.path.insert(0, SCRIPTS)

import lit_common  # noqa: E402


class TestDoiNormalisation(unittest.TestCase):
    def test_bare_doi_is_lowercased(self):
        self.assertEqual(lit_common.norm_doi("10.1186/S12967-024-06057-Y"), "10.1186/s12967-024-06057-y")

    def test_url_and_prefix_variants_collapse(self):
        variants = [
            "https://doi.org/10.1186/s12967-024-06057-y",
            "http://dx.doi.org/10.1186/S12967-024-06057-Y",
            "doi: 10.1186/s12967-024-06057-y",
            "  10.1186/s12967-024-06057-y.  ",
            "10.1186/s12967-024-06057-y",
        ]
        self.assertEqual({lit_common.norm_doi(v) for v in variants},
                         {"10.1186/s12967-024-06057-y"})

    def test_unusable_values_become_empty(self):
        for value in ["", None, "not a doi", "10.1/abc", "https://example.org/paper"]:
            self.assertEqual(lit_common.norm_doi(value), "", value)

    def test_pmid_extraction(self):
        self.assertEqual(lit_common.norm_pmid("40181378"), "40181378")
        self.assertEqual(lit_common.norm_pmid("PMID: 40181378"), "40181378")
        self.assertEqual(lit_common.norm_pmid(40181378), "40181378")
        self.assertEqual(lit_common.norm_pmid("abc"), "")


class TestTitleNormalisation(unittest.TestCase):
    def test_punctuation_and_case_ignored(self):
        self.assertEqual(lit_common.norm_title("Radiomics — in Lung Cancer!"),
                         "radiomics in lung cancer")

    def test_similarity(self):
        self.assertEqual(lit_common.title_similarity("Radiomics in lung cancer",
                                                     "Radiomics in lung cancer."), 1.0)
        self.assertGreater(lit_common.title_similarity(
            "Deep learning for lung cancer prognosis",
            "Deep learning for lung cancer prognosis in a multicentre cohort"), 0.7)
        self.assertLess(lit_common.title_similarity(
            "Deep learning for lung cancer prognosis",
            "A completely different paper about aortic dissection"), 0.4)

    def test_empty_title_is_not_equal_to_empty_title(self):
        self.assertEqual(lit_common.title_similarity("", ""), 0.0)


class TestMerge(unittest.TestCase):
    def test_missing_fields_are_rescued(self):
        base = {"doi": "10.1186/x", "abstract": "short", "source_platform": "pubmed"}
        incoming = {"doi": "10.1186/x", "abstract": "a much longer and richer abstract",
                    "citation_count": 42, "source_platform": "openalex"}
        merged = lit_common.merge_records(base, incoming)
        self.assertEqual(merged["abstract"], "a much longer and richer abstract")
        self.assertEqual(merged["citation_count"], 42)
        self.assertEqual(sorted(merged["sources"]), ["openalex", "pubmed"])

    def test_citation_count_keeps_maximum(self):
        merged = lit_common.merge_records({"citation_count": 10}, {"citation_count": 3})
        self.assertEqual(merged["citation_count"], 10)

    def test_existing_value_is_not_overwritten(self):
        merged = lit_common.merge_records({"journal": "Lancet"}, {"journal": "Other"})
        self.assertEqual(merged["journal"], "Lancet")


class TestDedupe(unittest.TestCase):
    def test_identifier_duplicates_merge(self):
        records, report = lit_common.dedupe([
            {"doi": "10.1186/S12967-024-06057-Y", "title": "A title long enough to be a title"},
            {"doi": "https://doi.org/10.1186/s12967-024-06057-y.",
             "title": "A title long enough to be a title", "citation_count": 9},
        ])
        self.assertEqual(len(records), 1)
        self.assertEqual(report["merged_by_identifier"], 1)
        self.assertEqual(report["duplicates_removed"], 1)
        self.assertEqual(records[0]["citation_count"], 9)

    def test_title_only_duplicate_is_merged_but_flagged(self):
        records, report = lit_common.dedupe([
            {"title": "Deep learning for lung cancer prognosis in a multicentre cohort"},
            {"title": "Deep learning for lung cancer prognosis in a multicentre cohort."},
        ])
        self.assertEqual(len(records), 1)
        self.assertEqual(report["merged_by_title_pending_review"], 1)
        self.assertEqual(records[0]["dedupe_basis"], "title")
        self.assertTrue(report["pending_review"])

    def test_different_identifiers_same_title_are_not_merged(self):
        records, report = lit_common.dedupe([
            {"doi": "10.1186/s12967-024-06057-y", "title": "Same title in both records here"},
            {"doi": "10.1000/182", "title": "Same title in both records here"},
        ])
        self.assertEqual(len(records), 2)
        self.assertEqual(len(report["review_candidates"]), 1)
        self.assertIn("preprint", report["review_candidates"][0]["note"])

    def test_short_titles_are_never_matched(self):
        records, report = lit_common.dedupe([{"title": "Editorial"}, {"title": "Editorial"}])
        self.assertEqual(len(records), 2)
        self.assertEqual(report["unkeyable"], 2)

    def test_chinese_titles_are_matched(self):
        # 16 CJK characters carry more information than 24 Latin characters, so a
        # Chinese title with no DOI must still be deduplicated.
        title = "肺结节放射组学模型的建立与验证"
        records, report = lit_common.dedupe([{"title": title}, {"title": title}])
        self.assertEqual(len(records), 1)
        self.assertEqual(report["merged_by_title_pending_review"], 1)

    def test_accounting_balances(self):
        records, report = lit_common.dedupe([
            {"doi": "10.1186/a"}, {"doi": "10.1186/a"},
            {"title": "Some sufficiently long title for the title path"},
            {"title": "Some sufficiently long title for the title path"},
            {"title": "Another sufficiently long title entirely different"},
        ])
        self.assertEqual(report["input"], 5)
        self.assertEqual(report["unique"], 3)
        self.assertEqual(report["input"], report["unique"] + report["duplicates_removed"])
        self.assertEqual(report["unkeyable"], 2)


class TestRecordIO(unittest.TestCase):
    def _write(self, text):
        handle, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.unlink, path)
        return path

    def test_plain_list(self):
        path = self._write(json.dumps([{"title": "a"}]))
        self.assertEqual(lit_common.load_records(path), [{"title": "a"}])

    def test_wrapped_object(self):
        path = self._write(json.dumps({"records": [{"title": "a"}], "meta": 1}))
        self.assertEqual(lit_common.load_records(path), [{"title": "a"}])

    def test_json_lines(self):
        path = self._write('{"title": "a"}\n{"title": "b"}\n')
        self.assertEqual(len(lit_common.load_records(path)), 2)

    def test_utf8_bom(self):
        path = self._write("\ufeff" + json.dumps([{"title": "肺结节"}]))
        self.assertEqual(lit_common.load_records(path)[0]["title"], "肺结节")


class TestXlsxDegradation(unittest.TestCase):
    def test_missing_openpyxl_returns_false_not_raise(self):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("openpyxl"):
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = fake_import
        try:
            handle, path = tempfile.mkstemp(suffix=".xlsx")
            os.close(handle)
            ok = lit_common.write_xlsx(path, ["a"], [[1]])
            os.unlink(path)
        finally:
            builtins.__import__ = real_import
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
