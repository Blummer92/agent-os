"""Bounded post-merge evidence: current merged commits, no historical claims."""
import os
import unittest
from unittest.mock import patch

from scripts.agent_os_post_merge_learning import report
from report_fixtures import DETAIL, SHA, VALIDATION, WORKFLOW_REF, ReportCase, commit, commits_page


class HistoryEvidenceTests(ReportCase):
    def test_historical_head_and_ci_are_explicitly_unexamined(self):
        reader = self.reader([commit(1, "feat(api): normal")])
        result = report.build_report(reader, SHA, 4101, 100)
        self.assertTrue(result["listed_commits_complete"])
        self.assertFalse(result["historical_head_coverage_complete"])
        self.assertFalse(result["historical_ci_or_review_examined"])
        self.assertNotIn("supporting_evidence", result)
        self.assertEqual(result["status"], "no-repair-leads-observed")
        self.assertEqual(reader.requests, [DETAIL, commits_page(1), VALIDATION])
        self.assertEqual(result["all_commit_shas"], [commit(1, "")["sha"]])
        self.assertEqual(
            {"historical_head_coverage_complete", "historical_ci_or_review_examined"},
            {key for key in result if key.startswith("historical_")},
        )
        self.assertIn(
            "Historical CI attempts, code reviews, and removed heads: **not examined**.",
            report.render_summary(result),
        )

    def test_missing_and_empty_analyzer_env_are_none(self):
        for env in ({}, {"GITHUB_SHA": "", "GITHUB_WORKFLOW_REF": ""}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                result = report.build_report(self.reader([commit(1, "docs(api): note")]), SHA, 4101, 100)
                self.assertIsNone(result["analyzer_sha"])
                self.assertIsNone(result["analyzer_workflow_ref"])
                self.assertEqual(result["merge_sha"], SHA)

    def test_analyzer_identity_is_captured(self):
        with patch.dict(os.environ, {
            "GITHUB_SHA": "a" * 40,
            "GITHUB_WORKFLOW_REF": WORKFLOW_REF,
        }):
            result = report.build_report(self.reader([commit(1, "feat(api): normal")]), SHA, 4101, 100)
        self.assertEqual(result["analyzer_sha"], "a" * 40)
        self.assertEqual(result["analyzer_workflow_ref"], WORKFLOW_REF)

    def test_validation_failure_is_not_a_successful_learning_run(self):
        reader = self.reader([commit(1, "feat(api): normal")], validation={
            "id": 100, "head_sha": SHA, "name": "Agent OS Validation Gate", "event": "push",
            "head_branch": "main", "status": "completed", "conclusion": "failure",
        })
        result = report.build_report(reader, SHA, 4101, 100)
        self.assertEqual(result["status"], "review-needed")
        self.assertEqual(result["validation"]["state"], "failure")
        self.assertFalse(result["publication_authorized"])


if __name__ == "__main__":
    unittest.main()
