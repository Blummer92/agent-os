"""Adversarial follow-up tests for merged PR learning report."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.agent_os_post_merge_learning import report

REPO = "Blummer92/agent-os"
SHA = "f" * 40

def commit(n, msg):
    return {"sha": f"{n:040x}", "commit": {"message": msg}}

def pr(n=2, merged=True, sha=SHA):
    return {"number": 4101, "commits": n,
            "merged_at": "2026-11-23T23:39:56Z" if merged else None,
            "merged": merged, "merge_commit_sha": sha,
            "base": {"ref": "main", "repo": {"full_name": REPO}}}

def run(sha=SHA, conclusion="success"):
    return {"head_sha": sha, "name": "Agent OS Validation Gate", "event": "push",
            "head_branch": "main", "status": "completed", "conclusion": conclusion,
            "html_url": "https://github.com/Blummer92/agent-os/actions/runs/100"}

class Reader:
    repository = REPO
    def __init__(self, records, metadata=None, validation=None):
        self.records = records
        self.metadata = metadata if metadata is not None else pr(len(records))
        self.validation = validation if validation is not None else run()
        self.requests = []
    def get(self, path):
        self.requests.append(path)
        if path == "/pulls/4101": return self.metadata
        if path.startswith("/pulls/4101/commits?"):
            page = int(path.rsplit("page=", 1)[1])
            return self.records[(page - 1)*100:page*100]
        if path == "/actions/runs/100": return self.validation
        if path == f"/commits/{SHA}/pulls?per_page=100": return [self.metadata]
        if "/reviews?" in path or "/comments?" in path: return []
        if "/check-runs?filter=all&per_page=100&page=" in path:
            return {"total_count": 0, "check_runs": []}
        if "/statuses?per_page=100&page=" in path: return []
        if "/timeline?per_page=100&page=" in path: return []
        raise AssertionError("unexpected read: " + path)

class FollowupReviewTests(unittest.TestCase):
    def test_non_merge_push_has_only_one_expected_read(self):
        reader = Reader([])
        calls = []
        def get(path):
            calls.append(path)
            self.assertEqual(path, f"/commits/{SHA}/pulls?per_page=100")
            return []
        reader.get = get
        self.assertEqual(report.build_report(reader, SHA, None, None)["status"], "not-applicable")
        self.assertEqual(calls, [f"/commits/{SHA}/pulls?per_page=100"])

    def test_requested_pr_identity_mismatch(self):
        reader = Reader([commit(1, "fix(api): repair")], metadata={**pr(1), "number": 4102})
        with self.assertRaisesRegex(report.EvidenceError, "requested-pr-identity-mismatch"):
            report.build_report(reader, SHA, 4101, None)

    def test_associated_pr_ambiguous(self):
        reader = Reader([])
        reader.get = lambda path: [pr(1), {**pr(1), "number": 4103}]
        with self.assertRaisesRegex(report.EvidenceError, "associated-pr-ambiguous"):
            report.build_report(reader, SHA, None, None)

    def test_wrong_base_and_foreign_repository(self):
        for base, code in (({"ref": "release", "repo": {"full_name": REPO}}, "base-not-main"),
                           ({"ref": "main", "repo": {"full_name": "someone/else"}}, "base-repository-mismatch")):
            with self.subTest(code=code), self.assertRaisesRegex(report.EvidenceError, code):
                report.build_report(Reader([commit(1, "fix(api): repair")],
                                           metadata={**pr(1), "base": base}), SHA, 4101, None)

    def test_group_budget_over_25_distinct_fix_scopes(self):
        records = [commit(i, f"fix(scope{i}): repair") for i in range(1, 27)]
        with self.assertRaisesRegex(report.EvidenceError, "learning-group-budget-exceeded"):
            report.build_report(Reader(records), SHA, 4101, None)

    def test_discussion_exact_budget_and_overflow(self):
        for last, expected in ((0, False), (1, True)):
            reader = Reader([commit(1, "feat(api): ordinary")])
            original = reader.get
            def get(path):
                if "/reviews?" in path or "/comments?" in path:
                    page = int(path.rsplit("page=", 1)[1])
                    return [{}] * (100 if page < 3 else last)
                return original(path)
            reader.get = get
            evidence = report.build_report(reader, SHA, 4101, None)["supporting_evidence"]
            with self.subTest(last=last):
                self.assertEqual(evidence["review_count_observed"], 200)
                self.assertIs(evidence["review_history_truncated"], expected)
                self.assertIs(evidence["issue_comment_history_truncated"], expected)

    def test_fix_heavy_history_keeps_ordered_regression_links(self):
        records = [commit(i, "fix(api): repair") for i in range(1, 27)]
        records += [commit(27, "test(api): regression"), commit(28, "test(api): negative")]
        lead = report.build_report(Reader(records), SHA, 4101, None)["review_leads"][0]
        self.assertEqual(len(lead["evidence_refs"]), report.MAX_REFS_PER_GROUP)
        for pos, n in enumerate((1, 27, 2, 28)):
            self.assertEqual(lead["evidence_refs"][pos], f"https://github.com/{REPO}/commit/{n:040x}")
        self.assertTrue(lead["evidence_truncated"])
        self.assertFalse(lead["reusable_rule_proven"])

    def test_render_summary_is_read_only(self):
        result = report.build_report(Reader([commit(1, "fix(api): repair")]), SHA, 4101, 100)
        summary = report.render_summary(result)
        self.assertIn("Listed PR commits: **1**", summary)
        self.assertIn("No lesson candidate, Notion write, activation, merge authority", summary)
        self.assertEqual(summary.count("Review needed (CKR5: not proven)"), 1)

    def test_main_writes_valid_receipt_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            summary = Path(tmp) / "summary.md"
            with patch.object(report, "GitHubReader", return_value=Reader([commit(1, "fix(api): repair")])), patch.dict(
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
            bad = Reader([commit(1, "fix(api): repair")], metadata={**pr(1), "merge_commit_sha": "0"*40})
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

    def test_workflow_preserves_read_only_and_fail_closed_receipts(self):
        path = Path(__file__).resolve().parents[2] / ".github/workflows/agent-os-post-merge-learning.yml"
        text = path.read_text()
        self.assertIn("permissions:\n  contents: read", text)
        self.assertNotIn("issues: write", text)
        self.assertNotIn("pull-requests: write", text)
        self.assertIn("if: always()", text)
        self.assertIn("if-no-files-found: warn", text)
        self.assertNotIn("continue-on-error: true", text)
        self.assertIn("--merge-sha", text)
        self.assertIn("--pr-number", text)

if __name__ == "__main__":
    unittest.main()
