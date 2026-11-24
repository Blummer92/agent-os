"""Regression controls for Opus's post-merge historical-evidence findings."""
import os
import unittest
from unittest.mock import patch

from scripts.agent_os_post_merge_learning import report
from test_report import Reader, SHA, REPO, commit


class HistoryEvidenceTests(unittest.TestCase):
    def test_rerun_failure_not_erased_by_success(self):
        reader = Reader([commit(1, "feat(api): normal")])
        original = reader.get
        def get(path):
            if "/check-runs?filter=all&per_page=100&page=" in path:
                self.assertIn("filter=all", path)
                return {"total_count": 2, "check_runs": [
                    {"conclusion": "failure", "html_url": f"https://github.com/{REPO}/actions/runs/1"},
                    {"conclusion": "success", "html_url": f"https://github.com/{REPO}/actions/runs/2"}]}
            return original(path)
        reader.get = get
        result = report.build_report(reader, SHA, 4101, 100)
        self.assertEqual(result["supporting_evidence"]["check_run_counts"]["failure"], 1)
        self.assertEqual(result["status"], "review-needed")
        self.assertFalse(result["historical_head_coverage_complete"])

    def test_timeout_only_is_attention_worthy(self):
        reader = Reader([commit(1, "feat(api): normal")])
        original = reader.get
        def get(path):
            if "/check-runs?filter=all&per_page=100&page=" in path:
                return {"total_count": 1, "check_runs": [{"conclusion": "timed_out", "html_url": None}]}
            return original(path)
        reader.get = get
        result = report.build_report(reader, SHA, 4101, 100)
        self.assertEqual(result["supporting_evidence"]["check_run_counts"]["attention"], 1)
        self.assertEqual(result["status"], "review-needed")

    def test_check_run_pagination_reaches_all_attempts(self):
        reader = Reader([commit(1, "feat(api): normal")])
        original = reader.get
        def get(path):
            if "/check-runs?filter=all&per_page=100&page=" in path:
                page = int(path.rsplit("page=", 1)[1])
                rows = [{"conclusion": "success"}] * 100 if page == 1 else [{"conclusion": "failure"}]
                return {"total_count": 101, "check_runs": rows}
            return original(path)
        reader.get = get
        result = report.build_report(reader, SHA, 4101, 100)
        self.assertEqual(result["supporting_evidence"]["check_run_counts"]["failure"], 1)
        self.assertEqual(result["supporting_evidence"]["check_run_counts"]["success"], 100)

    def test_force_push_is_reported_without_claiming_full_history(self):
        reader = Reader([commit(1, "feat(api): normal")])
        original = reader.get
        def get(path):
            if "/timeline?" in path:
                return [{"event": "head_ref_force_pushed"}]
            return original(path)
        reader.get = get
        result = report.build_report(reader, SHA, 4101, 100)
        self.assertTrue(result["supporting_evidence"]["rewritten_history_observed"])
        self.assertTrue(result["listed_commits_complete"])
        self.assertFalse(result["historical_head_coverage_complete"])
        self.assertNotIn("history_complete", result)
        self.assertEqual(result["status"], "review-needed")

    def test_inline_only_review_comment_is_counted(self):
        reader = Reader([commit(1, "feat(api): normal")])
        original = reader.get
        def get(path):
            if "/pulls/4101/comments?" in path:
                return [{"html_url": f"https://github.com/{REPO}/pull/4101#discussion_r1"}]
            return original(path)
        reader.get = get
        result = report.build_report(reader, SHA, 4101, 100)
        self.assertEqual(result["supporting_evidence"]["inline_comment_count_observed"], 1)
        self.assertEqual(len(result["supporting_evidence"]["inline_comment_refs"]), 1)
        self.assertEqual(result["status"], "review-needed")

    def test_legacy_failure_is_not_hidden_by_green_check(self):
        reader = Reader([commit(1, "feat(api): normal")])
        original = reader.get
        def get(path):
            if "/statuses?per_page=100&page=" in path:
                return [{"state": "failure"}]
            return original(path)
        reader.get = get
        result = report.build_report(reader, SHA, 4101, 100)
        self.assertEqual(result["supporting_evidence"]["legacy_status_counts"]["failure"], 1)
        self.assertEqual(result["status"], "review-needed")

    def test_analyzer_identity_is_captured(self):
        with patch.dict(os.environ, {"GITHUB_SHA": "a"*40,
                                     "GITHUB_WORKFLOW_REF": f"{REPO}/.github/workflows/agent-os-post-merge-learning.yml@refs/heads/main"}):
            result = report.build_report(Reader([commit(1, "feat(api): normal")]), SHA, 4101, 100)
        self.assertEqual(result["analyzer_sha"], "a"*40)
        self.assertIn("agent-os-post-merge-learning.yml", result["analyzer_workflow_ref"])

    def test_truncated_all_attempts_are_refused(self):
        reader = Reader([commit(1, "feat(api): normal")])
        original = reader.get
        def get(path):
            if "/check-runs?filter=all&per_page=100&page=" in path:
                return {"total_count": 2, "check_runs": [{"conclusion": "success"}]}
            return original(path)
        reader.get = get
        with self.assertRaisesRegex(report.EvidenceError, "check-run-evidence-incomplete"):
            report.build_report(reader, SHA, 4101, 100)


if __name__ == "__main__":
    unittest.main()
