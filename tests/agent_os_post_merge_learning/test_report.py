"""Read-only post-merge report: positive and hard-negative cases."""
import unittest
from scripts.agent_os_post_merge_learning import report

SHA = "f" * 40
REPO = "Blummer92/agent-os"

def commit(n, msg):
    return {"sha": f"{n:040x}", "commit": {"message": msg}}

def pr(n=2, merged=True, sha=SHA):
    return {"number": 4101, "commits": n, "merged_at": "2026-11-23T23:39:56Z" if merged else None,
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
        if path.endswith("/check-runs?per_page=100"):
            return {"total_count": 0, "check_runs": []}
        raise AssertionError(path)

class TestLearning(unittest.TestCase):
    def test_positive_review_lead_never_publishes(self):
        records = [commit(1, "fix(ckr2): reject title echo"), commit(2, "test(ckr2): hard negative")]
        result = report.build_report(Reader(records), SHA, 4101, 100)
        self.assertEqual(result["commit_count"], 2)
        self.assertEqual(result["validation"]["state"], "success")
        self.assertEqual(result["review_leads"][0]["scope"], "ckr2")
        self.assertEqual(result["review_leads"][0]["ckr5_reason_codes"], ["reusable-rule-not-proven"])
        self.assertIsNone(result["lesson_proposal"])
        self.assertFalse(result["publication_authorized"])

    def test_positive_ordinary_pr_creates_no_lead(self):
        result = report.build_report(Reader([commit(1, "feat(api): feature"),
                                             commit(2, "test(api): coverage")]), SHA, 4101, 100)
        self.assertEqual(result["status"], "no-repair-leads-observed")
        self.assertEqual(result["review_leads"], [])

    def test_negative_failed_validation_never_publishes(self):
        result = report.build_report(Reader([commit(1, "fix(api): repair")],
                                            validation=run(conclusion="failure")), SHA, 4101, 100)
        self.assertEqual(result["validation"]["state"], "failure")
        self.assertFalse(result["publication_authorized"])

    def test_negative_wrong_validation_identity(self):
        with self.assertRaisesRegex(report.EvidenceError, "validation-run-identity-mismatch"):
            report.build_report(Reader([commit(1, "fix(api): repair")],
                                       validation=run(sha="0"*40)), SHA, 4101, 100)

    def test_negative_unmerged_and_wrong_sha(self):
        for metadata in (pr(1, merged=False), pr(1, sha="0"*40)):
            with self.subTest(metadata=metadata), self.assertRaises(report.EvidenceError):
                report.build_report(Reader([commit(1, "fix(api): repair")], metadata=metadata), SHA, 4101, 100)

    def test_negative_incomplete_history(self):
        with self.assertRaisesRegex(report.EvidenceError, "commit-history-incomplete"):
            report.build_report(Reader([commit(1, "fix(api): repair")], metadata=pr(2)), SHA, 4101, 100)

    def test_negative_duplicate_commit(self):
        c = commit(1, "fix(api): repair")
        with self.assertRaisesRegex(report.EvidenceError, "commit-history-identity-invalid"):
            report.build_report(Reader([c, c]), SHA, 4101, 100)

    def test_positive_pagination(self):
        records = [commit(i, "feat(api): routine") for i in range(1, 203)]
        reader = Reader(records)
        result = report.build_report(reader, SHA, 4101, None)
        self.assertEqual(result["commit_count"], 202)
        self.assertIn("/pulls/4101/commits?per_page=100&page=3", reader.requests)

    def test_negative_check_page_incomplete(self):
        reader = Reader([commit(1, "fix(api): repair")])
        original = reader.get
        reader.get = lambda p: {"total_count": 2, "check_runs": []} if p.endswith("/check-runs?per_page=100") else original(p)
        with self.assertRaisesRegex(report.EvidenceError, "check-run-evidence-incomplete"):
            report.build_report(reader, SHA, 4101, 100)

    def test_negative_budget(self):
        with self.assertRaisesRegex(report.EvidenceError, "commit-count-out-of-bounds"):
            report.build_report(Reader([], metadata=pr(251)), SHA, 4101, 100)

    def test_positive_non_merge_push(self):
        reader = Reader([])
        reader.get = lambda path: [] if path.endswith("/pulls?per_page=100") else reader.metadata
        self.assertEqual(report.build_report(reader, SHA, None, 100)["status"], "not-applicable")

    def test_negative_bounded_evidence(self):
        records = [commit(i, "fix(api): repair") for i in range(1, 27)]
        lead = report.build_report(Reader(records), SHA, 4101, 100)["review_leads"][0]
        self.assertTrue(lead["evidence_truncated"])
        self.assertEqual(len(lead["evidence_refs"]), 20)
        self.assertFalse(lead["reusable_rule_proven"])

    def test_negative_invalid_message(self):
        with self.assertRaisesRegex(report.EvidenceError, "commit-message-invalid"):
            report.build_report(Reader([{"sha": "1"*40, "commit": {"message": 3}}]), SHA, 4101, 100)
