"""Read-only post-merge report: positive and hard-negative cases."""
from copy import deepcopy
import io
import urllib.error
from unittest.mock import patch
from scripts.agent_os_post_merge_learning import report
from report_fixtures import (
    ASSOCIATION, DETAIL, REPO, SHA, VALIDATION, ReportCase, commit, commits_page, pr, run,
)

class TestLearning(ReportCase):
    def test_positive_review_lead_never_publishes(self):
        records = [commit(1, "fix(ckr2): reject title echo"), commit(2, "test(ckr2): hard negative")]
        reader = self.reader(records)
        result = report.build_report(reader, SHA, 4101, 100)
        self.assertEqual(reader.requests, [DETAIL, commits_page(1), VALIDATION])
        self.assertEqual(result["all_commit_shas"], [r["sha"] for r in records])
        self.assertEqual(result["commit_count"], 2)
        self.assertEqual(result["validation"]["state"], "success")
        self.assertEqual(result["review_leads"][0]["scope"], "ckr2")
        self.assertEqual(result["review_leads"][0]["ckr5_reason_codes"], ["reusable-rule-not-proven"])
        self.assertIsNone(result["lesson_proposal"])
        self.assertFalse(result["publication_authorized"])

    def test_summary_provides_one_manual_lesson_draft_checklist(self):
        reader = self.reader([commit(1, "fix(api): repair"), commit(2, "fix(ckr2): repair")])
        result = report.build_report(reader, SHA, 4101, 100)
        self.assertEqual(len(result["review_leads"]), 2)
        before = deepcopy(result)
        reads = reader.requests.copy()
        summary = report.render_summary(result)
        self.assertEqual(summary.count("### Draft review checklist"), 1)
        for prompt in ("One reusable action", "When it applies", "When it does not apply",
                       "One source-linked example", "check for an existing lesson"):
            self.assertIn(prompt, summary)
        self.assertIn("Commit message patterns only identify possible review leads", summary)
        self.assertEqual(reader.requests, reads)
        self.assertEqual(result, before)
        self.assertIsNone(result["lesson_proposal"])
        self.assertTrue(all(x["lesson_proposal"] is None for x in result["review_leads"]))
        self.assertFalse(result["publication_authorized"])

    def test_summary_omits_lesson_checklist_without_repair_leads(self):
        records = [commit(1, "docs(api): clarify")]
        for conclusion in ("success", "failure"):
            with self.subTest(conclusion=conclusion):
                result = report.build_report(
                    self.reader(records, validation=run(conclusion=conclusion)), SHA, 4101, 100
                )
                self.assertEqual(result["review_leads"], [])
                self.assertNotIn("Draft review checklist", report.render_summary(result))

    def test_positive_ordinary_pr_creates_no_lead(self):
        result = report.build_report(self.reader([commit(1, "feat(api): feature"),
                                             commit(2, "test(api): coverage")]), SHA, 4101, 100)
        self.assertEqual(result["status"], "no-repair-leads-observed")
        self.assertEqual(result["review_leads"], [])

    def test_negative_failed_validation_never_publishes(self):
        result = report.build_report(self.reader([commit(1, "fix(api): repair")],
                                            validation=run(conclusion="failure")), SHA, 4101, 100)
        self.assertEqual(result["validation"]["state"], "failure")
        self.assertFalse(result["publication_authorized"])

    def test_negative_wrong_validation_identity(self):
        with self.evidence_error("validation-run-identity-mismatch"):
            report.build_report(self.reader([commit(1, "fix(api): repair")],
                                       validation=run(sha="0"*40)), SHA, 4101, 100)

    def test_negative_unmerged_and_wrong_sha(self):
        for metadata, code in ((pr(1, merged=False), "pr-not-merged"),
                               (pr(1, sha="0"*40), "merge-sha-mismatch")):
            with self.subTest(metadata=metadata), self.evidence_error(code):
                report.build_report(self.reader([commit(1, "fix(api): repair")], metadata=metadata), SHA, 4101, 100)

    def test_negative_incomplete_history(self):
        with self.evidence_error("commit-history-incomplete"):
            report.build_report(self.reader([commit(1, "fix(api): repair")], metadata=pr(2)), SHA, 4101, 100)

    def test_negative_duplicate_commit(self):
        c = commit(1, "fix(api): repair")
        with self.evidence_error("commit-history-identity-invalid"):
            report.build_report(self.reader([c, c]), SHA, 4101, 100)

    def test_positive_pagination(self):
        records = [commit(i, "feat(api): routine") for i in range(1, 203)]
        reader = self.reader(records)
        result = report.build_report(reader, SHA, 4101, None)
        self.assertEqual(result["commit_count"], 202)
        self.assertEqual(reader.requests, [DETAIL, commits_page(1), commits_page(2), commits_page(3)])
        self.assertEqual(result["all_commit_shas"], [row["sha"] for row in records])

    def test_negative_budget(self):
        with self.evidence_error("commit-count-out-of-bounds"):
            report.build_report(self.reader([], metadata=pr(251)), SHA, 4101, 100)

    def test_automatic_no_merge_has_no_history_reads(self):
        reader = self.reader([], associations=[])
        result = report.build_report(reader, SHA, None, 100)
        self.assertEqual(result["status"], "not-applicable")
        self.assertEqual(reader.requests, [ASSOCIATION])
        self.assertIs(result["publication_authorized"], False)
        self.assertIsNone(result["lesson_proposal"])

    def test_automatic_report_resolves_compact_association_before_review(self):
        rows = [commit(1, "fix(api): repair")]
        compact = {"number": 4101, "merged_at": pr()["merged_at"], "merge_commit_sha": SHA}
        reader = self.reader(rows, associations=[compact])
        result = report.build_report(reader, SHA, None, 100)
        self.assertEqual(result["pr_number"], 4101)
        self.assertEqual(reader.requests, [ASSOCIATION, DETAIL, commits_page(1), VALIDATION])
        self.assertIn("Draft review checklist", report.render_summary(result))
        self.assertIsNone(result["lesson_proposal"])

    def test_automatic_mismatched_detail_stops_after_two_reads(self):
        compact = {"number": 4101, "merged_at": pr()["merged_at"], "merge_commit_sha": SHA}
        reader = self.reader([], metadata={**pr(1), "number": 123}, associations=[compact])
        with self.evidence_error("requested-pr-identity-mismatch"):
            report.build_report(reader, SHA, None, 100)
        self.assertEqual(reader.requests, [ASSOCIATION, DETAIL])

    def test_automatic_invalid_associated_number_does_not_fetch_detail(self):
        for number in (True, False, "4101", 4101.0, None, 0):
            with self.subTest(number=number):
                compact = {"number": number, "merged_at": pr()["merged_at"], "merge_commit_sha": SHA}
                reader = self.reader([], associations=[compact])
                with self.evidence_error("pr-number-invalid"):
                    report.build_report(reader, SHA, None, 100)
                self.assertEqual(reader.requests, [ASSOCIATION])

    def test_negative_bounded_evidence(self):
        records = [commit(i, "fix(api): repair") for i in range(1, 27)]
        lead = report.build_report(self.reader(records), SHA, 4101, 100)["review_leads"][0]
        self.assertTrue(lead["evidence_truncated"])
        self.assertEqual(len(lead["evidence_refs"]), 20)
        self.assertFalse(lead["reusable_rule_proven"])

    def test_negative_invalid_message(self):
        with self.evidence_error("commit-message-invalid"):
            report.build_report(self.reader([{"sha": "1"*40, "commit": {"message": 3}}]), SHA, 4101, 100)


    def test_invalid_commit_counts_stop_before_history(self):
        for count in (0, True, False, -1, "1", 1.0, None, 251):
            code = "commit-count-out-of-bounds" if count == 251 else "pr-metadata-invalid"
            with self.subTest(count=count), self.evidence_error(code):
                reader = self.reader([], metadata={**pr(1), "commits": count})
                try:
                    report.build_report(reader, SHA, 4101, 100)
                finally:
                    self.assertEqual(reader.requests, [DETAIL])

    def test_validation_status_matrix(self):
        rows = [commit(1, "docs(api): note")]
        for expected in ("neutral", "action_required", "stale", "startup_failure",
                         "cancelled", "timed_out", "failure", "skipped"):
            with self.subTest(conclusion=expected):
                reader = self.reader(rows, validation=run(conclusion=expected))
                result = report.build_report(reader, SHA, 4101, 100)
                self.assertEqual(result["validation"]["state"], expected)
                self.assertEqual(result["status"], "review-needed")
                self.assertIsNone(result["lesson_proposal"])
        reader = self.reader(rows, validation={**run(conclusion=None), "status": "queued"})
        self.assertEqual(report.build_report(reader, SHA, 4101, 100)["validation"]["state"], "pending")
        reader = self.reader(rows, validation=None)
        self.assertEqual(report.build_report(reader, SHA, 4101, None)["validation"]["state"], "not-observed")
        self.assertEqual(reader.requests, [DETAIL, commits_page(1)])

    def test_validation_status_conflicts(self):
        for bad, code in (
            ({**run(), "conclusion": None}, "validation-run-status-invalid"),
            ({**run(), "status": "queued"}, "validation-run-status-conflict"),
            ({**run(), "status": ""}, "validation-run-status-invalid"),
        ):
            with self.subTest(bad=bad), self.evidence_error(code):
                reader = self.reader([commit(1, "docs(api): note")], validation=bad)
                report.build_report(reader, SHA, 4101, 100)

    def test_validation_checks_each_identity_field(self):
        for field, value in (("head_sha", "0"*40), ("name", "Other run"),
                             ("event", "pull_request"), ("head_branch", "dev")):
            with self.subTest(field=field), self.evidence_error("validation-run-identity-mismatch"):
                reader = self.reader([commit(1, "docs(api): note")], validation={**run(), field: value})
                report.build_report(reader, SHA, 4101, 100)

    def test_sha_rejects_non_hex_wrong_length_and_non_string(self):
        for value in ("z"*40, "f"*39, "f"*41, 123, None, SHA+"\n"):
            with self.subTest(value=value), self.evidence_error("invalid-sha"):
                reader = self.reader([])
                try:
                    report.build_report(reader, value, 4101, None)
                finally:
                    self.assertEqual(reader.requests, [])

    def test_explicit_validation_run_must_not_be_missing(self):
        reader = self.reader([commit(1, "fix(api): repair")], validation=None)
        with self.evidence_error("validation-run-evidence-missing"):
            report.build_report(reader, SHA, 4101, 100)
        self.assertEqual(reader.requests, [DETAIL, commits_page(1), VALIDATION])

    def test_bad_commit_row_fails_closed(self):
        reader = self.reader([commit(1, "fix(api): repair")])
        reader.responses[commits_page(1)] = ["not-a-commit"]
        with self.evidence_error("commit-list-malformed"):
            report.build_report(reader, SHA, 4101, 100)

    def test_uppercase_sha_normalizes(self):
        self.assertEqual(report._sha("F" * 40), SHA)
        self.assertEqual(report.build_report(self.reader([commit(1, "feat(api): normal")]), "F" * 40, 4101, None)["merge_sha"], SHA)

    def test_fix_heavy_evidence_preserves_test_links(self):
        records = [commit(i, "fix(api): repair") for i in range(1, 24)]
        records += [commit(24, "test(api): regression"), commit(25, "test(api): hard negative")]
        lead = report.build_report(self.reader(records), SHA, 4101, None)["review_leads"][0]
        self.assertTrue(lead["evidence_truncated"])
        self.assertEqual(len(lead["evidence_refs"]), report.MAX_REFS_PER_GROUP)
        self.assertEqual(lead["evidence_refs"][:4], [
            f"https://github.com/{REPO}/commit/{n:040x}" for n in (1, 24, 2, 25)
        ])

    def test_markdown_cell_escaping(self):
        result = report.build_report(self.reader([commit(1, "fix(api): repair")]), SHA, 4101, None)
        result["review_leads"][0]["scope"] = "bad|row\nnext"
        self.assertIn("bad\\|row next", report.render_summary(result))

    def test_http_errors_have_bounded_reason_codes(self):
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
                with self.evidence_error(reason):
                    reader.get("/pulls/4101")

    def test_public_reader_get_does_not_send_a_token(self):
        reader = report.GitHubReader(REPO)
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(b'{"number":4101}')
            self.assertEqual(reader.get(DETAIL), {"number": 4101})
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, f"https://api.github.com/repos/{REPO}{DETAIL}")
        self.assertFalse(request.has_header("Authorization"))

    def test_redirect_handler_refuses_forwarding(self):
        for code in (301, 302, 303, 307, 308):
            with self.subTest(code=code):
                self.assertIsNone(report._RejectRedirects().redirect_request(
                    None, None, code, "redirect", {}, "https://example.invalid"
                ))
