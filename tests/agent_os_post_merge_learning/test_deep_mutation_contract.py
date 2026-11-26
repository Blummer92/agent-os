"""Exercise read-only exact evidence, CKR5 boundary, and the real workflow shell."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import yaml

from report_fixtures import DETAIL, REPO, SHA, ReportCase, commit, repo_root
from scripts.agent_os_post_merge_learning import report


class DeepMutationContractTests(ReportCase):
    def test_null_pr_detail_is_invalid_before_history(self):
        reader = self.reader([], metadata=None)
        with self.evidence_error("pr-not-merged"):
            report.build_report(reader, SHA, 4101, None)
        self.assertEqual(reader.requests, [DETAIL])

    def test_no_authority_on_report_or_group(self):
        result = report.build_report(
            self.reader([commit(1, "fix(api): repair"), commit(2, "test(api): verify")]),
            SHA, 4101, 100,
        )
        for field in ("authority_created", "publication_authorized", "merge_authorized",
                      "closure_authorized", "notion_write_performed", "github_write_performed"):
            with self.subTest(field=field):
                self.assertIs(result[field], False)
        self.assertIsNone(result["lesson_proposal"])
        self.assertEqual(len(result["review_leads"]), 1)
        self.assertIs(result["review_leads"][0]["reusable_rule_proven"], False)
        self.assertIsNone(result["review_leads"][0]["lesson_proposal"])

    def test_CKR5_refusal_and_observation_checks_are_independent(self):
        from types import SimpleNamespace

        for disposition, observation in (
            (report.ProducerDisposition.MANUAL_REVIEW, None),
            (report.ProducerDisposition.NOT_REUSABLE, object()),
        ):
            with self.subTest(disposition=disposition), patch.object(
                report, "normalize_learning_outcome",
                return_value=SimpleNamespace(disposition=disposition, observation=observation, reason_codes=()),
            ) as evaluate:
                reader = self.reader([commit(1, "fix(api): repair")])
                with self.evidence_error("unverified-ckr5-candidate-not-blocked"):
                    report.build_report(reader, SHA, 4101, 100)
                evaluate.assert_called_once()
                signal = evaluate.call_args.args[0]
                self.assertIs(signal.reusable_rule_proven, False)
                self.assertFalse(signal.what_to_do_next_time)
                self.assertFalse(signal.guardrail)

    def test_http_oversize_and_exhaustion_are_distinct(self):
        reader = report.GitHubReader(REPO)
        with patch.object(report.urllib.request, "build_opener") as factory:
            opener = factory.return_value
            opener.open.return_value = io.BytesIO(b"[" + b" " * 1_999_999 + b"]")
            with self.evidence_error("github-response-too-large"):
                reader.get(DETAIL)
            opener.open.side_effect = urllib.error.HTTPError(
                f"https://api.github.com/repos/{REPO}{DETAIL}", 403,
                "internal", {"X-RateLimit-Remaining": "0"}, None,
            )
            with self.evidence_error("github-read-rate-limited"):
                reader.get(DETAIL)

    def test_transport_installs_real_redirect_rejection(self):
        reader = report.GitHubReader(REPO)
        with patch.object(report.urllib.request, "build_opener") as factory:
            factory.return_value.open.return_value = io.BytesIO(b'{"number":4101}')
            self.assertEqual(reader.get(DETAIL), {"number": 4101})
        factory.assert_called_once_with(report._RejectRedirects)

    def test_non_json_number_is_not_a_success_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            with patch.object(report, "build_report", return_value={
                "status": "not-applicable", "synthetic_invalid_number": float("nan"),
            }), patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(Path(tmp) / "summary.md")}):
                rc = report.main(["--repository", REPO, "--merge-sha", SHA, "--output", str(out)])
            self.assertEqual(rc, 2)
            evidence = json.loads(out.read_text())
            self.assertEqual(evidence["reason_code"], "report-generation-failed")
            self.assertIsNone(evidence["lesson_proposal"])
            self.assertIs(evidence["publication_authorized"], False)


class WorkflowBehaviorTests(unittest.TestCase):
    def setUp(self):
        flow = repo_root() / ".github/workflows/agent-os-post-merge-learning.yml"
        self.parsed = yaml.load(flow.read_text(), Loader=yaml.BaseLoader)
        self.job = self.parsed["jobs"]["review"]
        self.analysis = next(s for s in self.job["steps"] if s.get("name") == "Read-only exact-merge analysis")

    def test_workflow_scope_and_analyzer_revision(self):
        self.assertEqual(self.job["if"], (
            "${{ github.event_name == 'workflow_dispatch' || "
            "(github.event.workflow_run.event == 'push' && github.event.workflow_run.head_branch == 'main') }}"
        ))
        checkout = self.job["steps"][0]
        self.assertTrue(checkout["uses"].startswith("actions/checkout@"))
        self.assertEqual(checkout["with"], {"ref": "${{ github.sha }}", "persist-credentials": "false"})
        self.assertEqual(self.analysis["env"]["RUN_MERGE_SHA"], "${{ github.event.workflow_run.head_sha }}")
        self.assertEqual(self.analysis["env"]["RUN_ID"], "${{ github.event.workflow_run.id }}")

    def test_workflow_delivers_same_receipt_even_when_producer_fails(self):
        upload = next(s for s in self.job["steps"] if s.get("name") == "Upload evidence")
        self.assertEqual(upload["if"], "always()")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        self.assertEqual(upload["with"]["path"], "${{ runner.temp }}/post-merge-learning/report.json")
        self.assertEqual(self.parsed["permissions"], {"contents": "read"})

    def test_workflow_shell_uses_event_inputs_and_propagates_manual_review_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python = root / "python"
            python.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$TRACE"\nexit "$STUB_STATUS"\n')
            python.chmod(0o700)
            env = {
                **os.environ, "PATH": f"{root}:{os.environ['PATH']}", "REPOSITORY": REPO,
                "EVENT_NAME": "workflow_run", "RUNNER_TEMP": str(root), "RUN_MERGE_SHA": SHA,
                "RUN_ID": "100", "INPUT_PR": "4101", "INPUT_MERGE_SHA": "0" * 40,
                "INPUT_VALIDATION_RUN_ID": "200", "STUB_STATUS": "2", "TRACE": str(root / "trace"),
            }
            prefix = ["-m", "scripts.agent_os_post_merge_learning.report", "--repository",
                      REPO, "--output", str(root / "post-merge-learning/report.json")]
            for event, suffix in (
                ("workflow_run", ["--merge-sha", SHA, "--validation-run-id", "100"]),
                ("workflow_dispatch", ["--pr-number", "4101", "--merge-sha", "0" * 40,
                                       "--validation-run-id", "200"]),
            ):
                with self.subTest(event=event):
                    result = subprocess.run(["bash", "-c", self.analysis["run"]],
                                            env={**env, "EVENT_NAME": event}, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual((root / "trace").read_text().splitlines(), prefix + suffix)


class ValidationRunBindingTests(ReportCase):
    def test_missing_or_different_run_id_never_counts_as_success(self):
        from report_fixtures import VALIDATION, commits_page, run

        for returned in (101, True, "100", None):
            with self.subTest(returned=returned):
                evidence = {**run(), "id": returned}
                if returned is None:
                    del evidence["id"]
                reader = self.reader([commit(1, "docs(api): no repair")], validation=evidence)
                with self.evidence_error("validation-run-identity-mismatch"):
                    report.build_report(reader, SHA, 4101, 100)
                self.assertEqual(reader.requests, [DETAIL, commits_page(1), VALIDATION])
