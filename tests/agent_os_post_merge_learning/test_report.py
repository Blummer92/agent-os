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
        def exact_get(path):
            self.assertEqual(path, f"/commits/{SHA}/pulls?per_page=100")
            return []
        reader.get = exact_get
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


    def test_invalid_commit_counts_fail_as_metadata(self):
        for count in (0, True, False, -1):
            with self.subTest(count=count), self.assertRaisesRegex(report.EvidenceError, "pr-metadata-invalid"):
                report._validate_pr({**pr(1), "commits": count}, REPO, SHA)

    def test_terminal_validation_non_success_and_pending_conflict(self):
        for state in ("neutral", "action_required", "stale", "startup_failure"):
            self.assertEqual(report._validate_run({**run(), "conclusion": state}, SHA)["state"], state)
        for bad in ({**run(), "conclusion": None},
                    {**run(), "status": "queued", "conclusion": "success"}):
            with self.assertRaises(report.EvidenceError):
                report._validate_run(bad, SHA)

    def test_explicit_validation_run_must_not_be_missing(self):
        reader = Reader([commit(1, "fix(api): repair")])
        original = reader.get
        reader.get = lambda path: None if path == "/actions/runs/100" else original(path)
        with self.assertRaisesRegex(report.EvidenceError, "validation-run-evidence-missing"):
            report.build_report(reader, SHA, 4101, 100)

    def test_discussion_truncation_is_visible(self):
        reader = Reader([commit(1, "feat(api): normal")])
        original = reader.get
        def get(path):
            if "/reviews?" in path or "/comments?" in path:
                page = int(path.rsplit("page=", 1)[1])
                return [{}] * (3 if page == 3 else 100)
            return original(path)
        reader.get = get
        result = report.build_report(reader, SHA, 4101, None)
        evidence = result["supporting_evidence"]
        self.assertEqual(evidence["review_count_observed"], 200)
        self.assertTrue(evidence["review_history_truncated"])
        self.assertTrue(evidence["issue_comment_history_truncated"])
        self.assertEqual(result["status"], "review-needed")

    def test_failed_check_links_missing_is_not_truncation(self):
        reader = Reader([commit(1, "fix(api): repair")])
        original = reader.get
        def get(path):
            if path.endswith("/check-runs?per_page=100"):
                return {"total_count": 2, "check_runs": [
                    {"conclusion": "failure", "html_url": None},
                    {"conclusion": "failure", "html_url": "https://example.org/other"}]}
            return original(path)
        reader.get = get
        evidence = report.build_report(reader, SHA, 4101, None)["supporting_evidence"]
        self.assertEqual(evidence["failed_check_refs_unavailable"], 2)
        self.assertFalse(evidence["failed_check_refs_truncated"])

    def test_failed_check_budget_is_explicit(self):
        reader = Reader([commit(1, "fix(api): repair")])
        original = reader.get
        def get(path):
            if path.endswith("/check-runs?per_page=100"):
                return {"total_count": 32, "check_runs": [
                    {"conclusion": "failure", "html_url": "https://github.com/Blummer92/agent-os/runs/123"}] * 32}
            return original(path)
        reader.get = get
        evidence = report.build_report(reader, SHA, 4101, None)["supporting_evidence"]
        self.assertEqual(len(evidence["failed_check_refs"]), 30)
        self.assertTrue(evidence["failed_check_refs_truncated"])

    def test_uppercase_sha_normalizes(self):
        self.assertEqual(report._sha("F" * 40), SHA)
        self.assertEqual(report.build_report(Reader([commit(1, "feat(api): normal")]), "F" * 40, 4101, None)["merge_sha"], SHA)

    def test_fix_heavy_evidence_preserves_test_links(self):
        records = [commit(i, "fix(api): repair") for i in range(1, 24)]
        records += [commit(24, "test(api): regression"), commit(25, "test(api): hard negative")]
        lead = report.build_report(Reader(records), SHA, 4101, None)["review_leads"][0]
        self.assertTrue(lead["evidence_truncated"])
        self.assertEqual(len(lead["evidence_refs"]), report.MAX_REFS_PER_GROUP)
        self.assertTrue(any(ref.endswith("/commit/" + f"{n:040x}") for n in (24, 25) for ref in lead["evidence_refs"]))

    def test_markdown_cell_escaping(self):
        result = report.build_report(Reader([commit(1, "fix(api): repair")]), SHA, 4101, None)
        result["review_leads"][0]["scope"] = "bad|row\nnext"
        self.assertIn("bad\\|row next", report.render_summary(result))

    def test_http_errors_have_bounded_reason_codes(self):
        import urllib.error
        from unittest.mock import patch
        reader = report.GitHubReader(REPO, "synthetic-token")
        class Opener:
            def __init__(self, code): self.code = code
            def open(self, request, timeout):
                raise urllib.error.HTTPError(request.full_url, self.code, "private", {}, None)
        for code, reason in ((301, "github-read-redirect-rejected"),
                             (401, "github-read-unauthorized"),
                             (403, "github-read-forbidden"),
                             (404, "github-read-not-found"),
                             (429, "github-read-rate-limited"),
                             (502, "github-read-upstream-error")):
            with self.subTest(code=code), patch("urllib.request.build_opener", return_value=Opener(code)):
                with self.assertRaisesRegex(report.EvidenceError, "^" + reason + "$"):
                    reader.get("/pulls/4101")

    def test_redirect_handler_refuses_forwarding(self):
        self.assertIsNone(report._RejectRedirects().redirect_request(None, None, 302, "redirect", {}, "https://evil.invalid"))
