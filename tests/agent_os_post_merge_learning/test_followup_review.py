"""Adversarial follow-up tests for merged PR learning report."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.agent_os_post_merge_learning import report
from report_fixtures import REPO, SHA, ReportCase, commit, pr

class FollowupReviewTests(ReportCase):
    def test_requested_pr_identity_mismatch(self):
        reader = self.reader([commit(1, "fix(api): repair")], metadata={**pr(1), "number": 4102})
        with self.evidence_error("requested-pr-identity-mismatch"):
            report.build_report(reader, SHA, 4101, None)

    def test_associated_pr_ambiguous(self):
        reader = self.reader([], associations=[pr(1), {**pr(1), "number": 4103}])
        with self.evidence_error("associated-pr-ambiguous"):
            report.build_report(reader, SHA, None, None)

    def test_wrong_base_and_foreign_repository(self):
        for base, code in (({"ref": "release", "repo": {"full_name": REPO}}, "base-not-main"),
                           ({"ref": "main", "repo": {"full_name": "someone/else"}}, "base-repository-mismatch")):
            with self.subTest(code=code), self.evidence_error(code):
                report.build_report(self.reader([commit(1, "fix(api): repair")],
                                           metadata={**pr(1), "base": base}), SHA, 4101, None)

    def test_group_budget_over_25_distinct_fix_scopes(self):
        records = [commit(i, f"fix(scope{i}): repair") for i in range(1, 27)]
        with self.evidence_error("learning-group-budget-exceeded"):
            report.build_report(self.reader(records), SHA, 4101, None)

    def test_fix_heavy_history_keeps_ordered_regression_links(self):
        records = [commit(i, "fix(api): repair") for i in range(1, 27)]
        records += [commit(27, "test(api): regression"), commit(28, "test(api): negative")]
        lead = report.build_report(self.reader(records), SHA, 4101, None)["review_leads"][0]
        self.assertEqual(len(lead["evidence_refs"]), report.MAX_REFS_PER_GROUP)
        for pos, n in enumerate((1, 27, 2, 28)):
            self.assertEqual(lead["evidence_refs"][pos], f"https://github.com/{REPO}/commit/{n:040x}")
        self.assertTrue(lead["evidence_truncated"])
        self.assertFalse(lead["reusable_rule_proven"])

    def test_render_summary_is_read_only(self):
        result = report.build_report(self.reader([commit(1, "fix(api): repair")]), SHA, 4101, 100)
        summary = report.render_summary(result)
        self.assertIn("Listed PR commits: **1**", summary)
        self.assertIn("No lesson candidate, Notion write, activation, merge authority", summary)
        self.assertEqual(summary.count("Review needed (CKR5: not proven)"), 1)

    def test_main_writes_valid_receipt_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            summary = Path(tmp) / "summary.md"
            with patch.object(report, "GitHubReader", return_value=self.reader([commit(1, "fix(api): repair")])), patch.dict(
                os.environ, {"GITHUB_TOKEN": "test", "GITHUB_STEP_SUMMARY": str(summary)}
            ):
                code = report.main(["--repository", REPO, "--merge-sha", SHA,
                                    "--pr-number", "4101", "--output", str(output)])
            self.assertEqual(code, 0)
            result = json.loads(output.read_text())
            self.assertEqual(result["status"], "review-needed")
            self.assertFalse(result["publication_authorized"])
            self.assertIn("Read-only post-merge learning analysis", summary.read_text())

    def test_main_manual_review_preserves_receipt_and_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            summary = Path(tmp) / "summary.md"
            bad = self.reader([commit(1, "fix(api): repair")], metadata={**pr(1), "merge_commit_sha": "0"*40})
            with patch.object(report, "GitHubReader", return_value=bad), patch.dict(
                os.environ, {"GITHUB_TOKEN": "test", "GITHUB_STEP_SUMMARY": str(summary)}
            ):
                code = report.main(["--repository", REPO, "--merge-sha", SHA,
                                    "--pr-number", "4101", "--output", str(output)])
            self.assertEqual(code, 2)
            result = json.loads(output.read_text())
            self.assertEqual(result["status"], "manual-review")
            self.assertEqual(result["reason_code"], "merge-sha-mismatch")
            self.assertFalse(result["notion_write_performed"])
            self.assertIn("manual review required", summary.read_text())


if __name__ == "__main__":
    unittest.main()
