"""Offline tests for the pure functions in literature.py and the CLI contract.

These guard the behaviours that used to fail silently: Chinese topics crashing
`extract`, Chinese abstracts extracting nothing, and `first_str(0)` dropping a
citation count of zero.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "literature-analysis", "scripts")
sys.path.insert(0, SCRIPTS)

import literature  # noqa: E402

CHINESE_ABSTRACT = (
    "目的：探讨肺结节放射组学特征对良恶性鉴别的价值。方法：回顾性纳入112例肺结节患者，"
    "采用外部验证队列评估模型。结果：AUC为0.87。结论：放射组学模型具有较好的诊断效能。"
    "本研究的局限在于样本量较小。"
)


class TestTopicScore(unittest.TestCase):
    def test_english_topic(self):
        score = literature.topic_score("radiomics lung cancer",
                                       "Radiomics features predict lung cancer prognosis")
        self.assertEqual(score, 1.0)

    def test_chinese_topic_no_longer_scores_zero(self):
        score = literature.topic_score("肺结节 放射组学", CHINESE_ABSTRACT)
        self.assertGreaterEqual(score, 0.7)

    def test_chinese_topic_literal_match(self):
        self.assertEqual(literature.topic_score("肺结节", "本文研究肺结节。"), 1.0)

    def test_russian_topic(self):
        score = literature.topic_score("радиомика", "Радиомика в диагностике опухолей")
        self.assertGreater(score, 0)

    def test_empty_topic_returns_none(self):
        self.assertIsNone(literature.topic_score("", "some text"))
        self.assertIsNone(literature.topic_score("a an the", "some text"))

    def test_fmt_score_handles_none(self):
        self.assertEqual(literature.fmt_score(None), "n/a")
        self.assertEqual(literature.fmt_score(0.5), "0.50")

    def test_relevance_bands(self):
        self.assertEqual(literature.topic_relevance(0.9), "High")
        self.assertEqual(literature.topic_relevance(0.5), "Medium")
        self.assertEqual(literature.topic_relevance(0.1), "Low")
        self.assertEqual(literature.topic_relevance(None), "unclear")


class TestChineseExtraction(unittest.TestCase):
    def test_design(self):
        self.assertEqual(literature.extract_study_design("回顾性分析"), "Retrospective cohort study")
        self.assertEqual(literature.extract_study_design("前瞻性队列研究"), "Prospective cohort study")
        self.assertEqual(literature.extract_study_design("系统评价与Meta分析"),
                         "Systematic review / meta-analysis")
        self.assertEqual(literature.extract_study_design("多中心回顾性研究"),
                         "Retrospective cohort study (multi-center)")

    def test_sample_size(self):
        self.assertEqual(literature.extract_sample_size("共纳入112例患者"), "112")
        self.assertEqual(literature.extract_sample_size("选取85名受试者"), "85")
        self.assertEqual(literature.extract_sample_size("we enrolled 240 patients"), "240")

    def test_validation(self):
        self.assertEqual(literature.extract_validation("并进行外部验证"), "External validation")
        self.assertEqual(literature.extract_validation("采用内部验证"), "Internal validation")

    def test_limitations(self):
        self.assertIn("样本量较小", literature.extract_limitations("本研究的局限在于样本量较小。"))

    def test_english_still_works(self):
        self.assertEqual(literature.extract_study_design("This retrospective cohort study"),
                         "Retrospective cohort study")


class TestHelpers(unittest.TestCase):
    def test_first_str_keeps_zero(self):
        self.assertEqual(literature.first_str(0), "0")
        self.assertEqual(literature.first_str(None), "")
        self.assertEqual(literature.first_str([]), "")
        self.assertEqual(literature.first_str(["a", "b"]), "a")

    def test_parse_dates(self):
        self.assertEqual(literature.parse_dates("2023/01/01:2026/08/05"),
                         ("2023/01/01", "2026/08/05"))
        self.assertEqual(literature.parse_dates("2023/01/01"), ("2023/01/01", None))
        self.assertEqual(literature.parse_dates(None), (None, None))

    def test_validate_query_flags_unbalanced(self):
        self.assertTrue(literature.validate_query('("a" OR "b"'))
        self.assertEqual(literature.validate_query('("a" OR "b")'), [])

    def test_evidence_level(self):
        self.assertEqual(literature.evidence_level("Systematic review / meta-analysis", ""), 2)
        self.assertEqual(literature.evidence_level("Randomized controlled trial", ""), 3)
        self.assertEqual(literature.evidence_level("Retrospective cohort study", "External validation"), 5)
        self.assertEqual(literature.evidence_level("", ""), "unclear")


class TestExtractCommand(unittest.TestCase):
    """The end-to-end extract path that used to crash on a Chinese topic."""

    def _run_extract(self, topic):
        records = [
            {"pmid": "1", "title": "肺结节放射组学诊断研究", "doi": "10.1186/x",
             "abstract": CHINESE_ABSTRACT, "pubDate": "2025", "journal": "中华放射学杂志"},
            {"pmid": "2", "title": "Aortic dissection outcomes", "doi": "10.1186/y",
             "abstract": "This retrospective study enrolled 50 patients with aortic dissection.",
             "pubDate": "2024", "journal": "J Vasc Surg"},
        ]
        tmpdir = tempfile.mkdtemp()
        src = os.path.join(tmpdir, "records.json")
        out = os.path.join(tmpdir, "overview.csv")
        with open(src, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False)
        args = type("Args", (), {"input": src, "out": out, "xlsx": None,
                                 "topic": topic, "include": None, "exclude": None})()
        literature.cmd_extract(args)
        with open(out, "r", encoding="utf-8-sig") as f:
            text = f.read()
        return text, tmpdir

    def test_chinese_topic_does_not_crash_and_relevance_is_high(self):
        text, _ = self._run_extract("肺结节 放射组学")
        self.assertIn("肺结节", text)
        self.assertNotIn("score n/a", text)
        self.assertIn("High", text)

    def test_evidence_column_is_populated(self):
        text, _ = self._run_extract("肺结节 放射组学")
        # The AUC sentence in the Chinese abstract must appear as a snippet.
        self.assertIn("AUC", text)

    def test_english_record_still_classified(self):
        text, _ = self._run_extract("aortic dissection")
        self.assertIn("Retrospective cohort study", text)


class TestCli(unittest.TestCase):
    def _python(self, *args):
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, "literature.py")] + list(args),
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=120)

    def test_version(self):
        proc = self._python("--version")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("literature-analysis", proc.stdout)

    def test_help_lists_new_commands(self):
        proc = self._python("--help")
        for command in ("verify", "prisma", "doctor", "dedupe"):
            self.assertIn(command, proc.stdout)

    def test_doctor_offline(self):
        proc = self._python("doctor", "--no-network")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Summary:", proc.stdout)
        self.assertIn("Python", proc.stdout)

    def test_search_all_requires_queries(self):
        proc = self._python("search-all", "--out", "unused.json")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("No queries provided", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
