"""Bounded post-merge evidence: current merged commits, no historical claims."""
import os
import unittest
from unittest.mock import patch

from scripts.agent_os_post_merge_learning import report
from test_report import Reader, SHA, REPO, commit


class HistoryEvidenceTests(unittest.TestCase):
    def test_historical_head_and_ci_are_explicitly_unexamined(self):
        reader = Reader([commit(1, "feat(api): normal")])
        result = report.build_report(reader, SHA, 4101, 100)
        self.assertTrue(result["listed_commits_complete"])
        self.assertFalse(result["historical_head_coverage_complete"])
        self.assertFalse(result["historical_ci_or_review_examined"])
        self.assertNotIn("supporting_evidence", result)
        self.assertEqual(result["status"], "no-repair-leads-observed")
        self.assertFalse(any(
            "/check-runs" in path or "/statuses" in path or "/reviews" in path
            or "/timeline" in path or "/comments" in path
            for path in reader.requests
        ))

    def test_analyzer_identity_is_captured(self):
        with patch.dict(os.environ, {
            "GITHUB_SHA": "a" * 40,
            "GITHUB_WORKFLOW_REF": (
                f"{REPO}/.github/workflows/agent-os-post-merge-learning.yml@refs/heads/main"
            ),
        }):
            result = report.build_report(Reader([commit(1, "feat(api): normal")]), SHA, 4101, 100)
        self.assertEqual(result["analyzer_sha"], "a" * 40)
        self.assertIn("agent-os-post-merge-learning.yml", result["analyzer_workflow_ref"])

    def test_validation_failure_is_not_a_successful_learning_run(self):
        reader = Reader([commit(1, "feat(api): normal")], validation={
            "head_sha": SHA, "name": "Agent OS Validation Gate", "event": "push",
            "head_branch": "main", "status": "completed", "conclusion": "failure",
        })
        result = report.build_report(reader, SHA, 4101, 100)
        self.assertEqual(result["status"], "review-needed")
        self.assertEqual(result["validation"]["state"], "failure")
        self.assertFalse(result["publication_authorized"])


if __name__ == "__main__":
    unittest.main()
