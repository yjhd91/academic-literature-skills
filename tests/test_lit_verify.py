"""Offline tests for reference verification (lit_verify.py).

The registry lookups are monkeypatched: these tests prove the *decision logic*,
not that Crossref is up. A separate live smoke test (scripts/smoke_test.py) covers
network reachability.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "literature-analysis", "scripts")
sys.path.insert(0, SCRIPTS)

import lit_verify  # noqa: E402

TITLE = "Habitat radiomics for progression free survival in non-small cell lung cancer"
DOI = "10.1186/s12967-024-06057-y"


def crossref(title=TITLE, year=2025):
    return {"source": "crossref", "title": title, "year": year,
            "journal": "J Transl Med", "doi": DOI, "type": "journal-article"}


def openalex(title=TITLE, year=2025):
    return {"source": "openalex", "title": title, "year": year,
            "journal": "Journal of Translational Medicine", "doi": DOI}


def pubmed(title=TITLE, year=2024):
    return {"source": "pubmed", "title": title, "year": year,
            "journal": "J Transl Med", "doi": DOI, "pmid": "40181378"}


class TestVerdicts(unittest.TestCase):
    def _verify(self, record, cross=True, oa=True, pm=True):
        with mock.patch.object(lit_verify, "crossref_by_doi", lambda doi: crossref() if cross else None), \
             mock.patch.object(lit_verify, "openalex_by_doi", lambda doi: openalex() if oa else None), \
             mock.patch.object(lit_verify, "pubmed_lookup", lambda **kw: pubmed() if pm else None), \
             mock.patch.object(lit_verify, "crossref_by_title", lambda *a, **k: None):
            return lit_verify.verify_record(record)

    def test_three_registries_and_matching_title_is_verified(self):
        result = self._verify({"title": TITLE, "doi": DOI, "year": 2025})
        self.assertEqual(result["verdict"], "verified")
        self.assertEqual(result["sources_resolved"], "crossref,openalex,pubmed")

    def test_single_registry_is_partial(self):
        result = self._verify({"title": TITLE, "doi": DOI}, oa=False, pm=False)
        self.assertEqual(result["verdict"], "partial")
        self.assertIn("only one registry", result["notes"])

    def test_wrong_title_is_mismatch_even_when_doi_resolves(self):
        result = self._verify({"title": "A completely different paper about aortic dissection",
                               "doi": DOI})
        self.assertEqual(result["verdict"], "mismatch")

    def test_nothing_resolves_is_not_found(self):
        result = self._verify({"title": TITLE, "doi": "10.9999/fake.12345"},
                              cross=False, oa=False, pm=False)
        self.assertEqual(result["verdict"], "not_found")
        self.assertIn("no registry returned", result["notes"])

    def test_year_mismatch_downgrades_to_mismatch(self):
        result = self._verify({"title": TITLE, "doi": DOI, "year": 2001})
        self.assertEqual(result["verdict"], "mismatch")
        self.assertIn("publication year", result["notes"])

    def test_year_within_tolerance_stays_verified(self):
        result = self._verify({"title": TITLE, "doi": DOI, "year": 2026})
        self.assertEqual(result["verdict"], "verified")

    def test_no_identifier(self):
        result = lit_verify.verify_record({})
        self.assertEqual(result["verdict"], "no_identifier")

    def test_doi_only_input_is_judged_on_resolution(self):
        result = self._verify({"doi": DOI})
        self.assertEqual(result["verdict"], "verified")
        self.assertIn("no input title", result["notes"])

    def test_doi_only_single_registry_is_partial(self):
        result = self._verify({"doi": DOI}, oa=False, pm=False)
        self.assertEqual(result["verdict"], "partial")


class TestBibtex(unittest.TestCase):
    def test_parse_basic_entry(self):
        handle, path = tempfile.mkstemp(suffix=".bib")
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            f.write("""
@article{wu2025habitat,
  title = {Habitat radiomics for progression free survival},
  doi = {10.1186/s12967-024-06057-y},
  year = {2025},
  journal = {J Transl Med},
  author = {Wu, Y and Zhang, W}
}
@inproceedings{other,
  title = "A conference paper",
  year = 2024
}
""")
        self.addCleanup(os.unlink, path)
        records = lit_verify.parse_bibtex(path)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["doi"], DOI)
        self.assertEqual(records[0]["year"], "2025")
        self.assertEqual(records[0]["journal"], "J Transl Med")
        self.assertEqual(records[1]["title"], "A conference paper")

    def test_entries_without_title_are_skipped(self):
        handle, path = tempfile.mkstemp(suffix=".bib")
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            f.write("@misc{nothing, note = {no title here}}\n")
        self.addCleanup(os.unlink, path)
        self.assertEqual(lit_verify.parse_bibtex(path), [])


class TestReport(unittest.TestCase):
    def test_markdown_lists_problem_references(self):
        results = [
            {"input_title": "ok", "input_year": 2025, "input_doi": DOI, "input_pmid": "",
             "verdict": "verified", "sources_resolved": "crossref,openalex",
             "best_title_similarity": 0.99, "source_year": 2025, "source_doi": DOI, "notes": ""},
            {"input_title": "bad", "input_year": 2025, "input_doi": "10.9999/fake",
             "input_pmid": "", "verdict": "not_found", "sources_resolved": "",
             "best_title_similarity": "", "source_year": "", "source_doi": "",
             "notes": "no registry returned this reference"},
        ]
        report = lit_verify.markdown_report(results, "refs.bib")
        self.assertIn("References requiring action", report)
        self.assertIn("10.9999/fake", report)
        self.assertIn("must not be cited", report)


if __name__ == "__main__":
    unittest.main()
