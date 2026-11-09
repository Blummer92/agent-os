"""Execute the workflow's report-only shell blocks, without GitHub or a publisher."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"


def render(name, **values):
    text = WORKFLOW.read_text()
    step = text.split(f"      - name: {name}\n", 1)[1]
    lines = step.split("        run: |\n", 1)[1].splitlines()
    shell = []
    for line in lines:
        if line and not line.startswith("          "):
            break
        shell.append(line[10:])
    with tempfile.TemporaryDirectory() as temp:
        summary = Path(temp) / "summary.md"
        env = dict(os.environ, PROFILE="", GITHUB_STEP_SUMMARY=str(summary),
                   GITHUB_SHA="b" * 40, PR_HEAD_SHA="a" * 40,
                   GITHUB_EVENT_NAME="pull_request", GITHUB_SERVER_URL="https://github.com",
                   GITHUB_REPOSITORY="Blummer92/agent-os", GITHUB_RUN_ID="123",
                   GITHUB_RUN_ATTEMPT="2", GITHUB_JOB="validate")
        env.update(values)
        # The only repository operation in either summary is this read-only identity query.
        bindir = Path(temp) / "bin"
        bindir.mkdir()
        git = bindir / "git"
        git.write_text('#!/bin/sh\nprintf "%s\\n" "' + "c" * 40 + '"\n')
        git.chmod(0o755)
        env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
        result = subprocess.run(["bash", "-eu", "-c", "\n".join(shell)],
                                env=env, text=True, capture_output=True, timeout=10)
        if result.returncode:
            raise AssertionError(result.stderr)
        return summary.read_text()


class SummaryTests(unittest.TestCase):
    def test_skipped_never_claims_authoritative_pass(self):
        text = render("Publish validation summary", AGGREGATE_OUTCOME="skipped")
        self.assertNotIn("Required PASS", text)
        self.assertNotIn("validation, including repository structure validation, executed", text)

    def test_focused_selection_does_not_claim_execution(self):
        text = render("Publish PR validation-plan summary", PROFILE="focused")
        self.assertNotIn("command set executed", text)
        self.assertIn("Execution is UNPROVEN", text)

    def test_deferred_is_incomplete(self):
        text = render("Publish PR validation-plan summary", PROFILE="aggregate")
        self.assertIn("Draft PR events defer", text)
        self.assertIn("NOT YET VERIFIED", text)

    def test_skipped_missing_and_malformed_outcomes_are_unproven(self):
        for outcome in ("", "skipped", "null", "unknown", "cancelled"):
            with self.subTest(outcome=outcome):
                text = render("Publish validation summary", AGGREGATE_OUTCOME=outcome)
                self.assertIn("UNPROVEN", text)
                self.assertNotIn("tests executed and failed", text)

    def test_step_success_is_not_test_or_status_certification(self):
        text = render("Publish validation summary", AGGREGATE_OUTCOME="success")
        self.assertIn("step completed", text)
        self.assertIn("not a test-evidence verdict", text)
        self.assertIn("NOT YET VERIFIED", text)

    def test_failure_does_not_invent_test_execution(self):
        text = render("Publish validation summary", AGGREGATE_OUTCOME="failure")
        self.assertNotIn("tests executed and failed", text)
        self.assertIn("candidate-or-runner", text)
        self.assertIn("manifest", text)

    def test_reuse_does_not_claim_rerun(self):
        text = render("Publish validation summary", RUN_REQUIRED="false", REUSE_STATE="success")
        self.assertIn("reused", text)
        self.assertIn("not-executed-in-this-run", text)
        self.assertNotIn("validation, including repository structure validation, executed", text)

    def test_missing_reuse_state_and_cancellation_do_not_certify_evidence(self):
        for state in ("", "missing", "error", "unknown", "success"):
            with self.subTest(state=state):
                text = render("Publish validation summary", RUN_REQUIRED="false", REUSE_STATE=state)
                self.assertIn("UNPROVEN by this summary", text)
                self.assertNotIn("exact-head aggregate evidence was reused", text)
        text = render("Publish validation summary", AGGREGATE_OUTCOME="cancelled")
        self.assertNotIn("was not executed", text)
        self.assertIn("execution is not established", text)

    def test_identity_and_evidence_are_locatable(self):
        text = render("Publish validation summary", AGGREGATE_OUTCOME="success")
        for value in ("a" * 40, "b" * 40, "c" * 40, "runs/123/attempts/2", "junit-aggregate-2"):
            self.assertIn(value, text)
        self.assertIn("not exact-head certification", text)

    def test_both_summaries_separate_required_and_pilot(self):
        for name in ("Publish validation summary", "Publish PR validation-plan summary"):
            with self.subTest(name=name):
                text = render(name)
                self.assertIn("agent-os/authoritative-aggregate", text)
                self.assertIn("agent-os/trusted-aggregate-pilot", text)
                self.assertIn("non-required", text)
                self.assertIn("NOT YET VERIFIED", text)
                self.assertIn("Only an explicit authority-file refusal", text)
                self.assertNotIn("Required PASS", text)


if __name__ == "__main__":
    unittest.main()
