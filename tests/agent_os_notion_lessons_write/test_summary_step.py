"""The Lessons write workflow's sanitized summary step exposes activation prerequisites safely.

Runs the workflow's own embedded Python (extracted from the YAML, so the test cannot
drift from the shipped step) against a temporary result.json. No network, no secrets.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/agent-os-notion-lessons-write.yml"
STEP_NAME = "Publish sanitized result summary"


def _step():
    value = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return next(step for step in value["jobs"]["lessons_write"]["steps"] if step.get("name") == STEP_NAME)


def _embedded_python():
    run = _step()["run"]
    head, _, rest = run.partition("<<'PY'\n")
    assert head.strip() == "python -", head
    return rest.rsplit("\nPY", 1)[0] if "\nPY" in rest else rest.rstrip().removesuffix("PY")


def render(result):
    """Execute the shipped step body; return the summary text it appends."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "agent-os-lessons-write"
        root.mkdir()
        if result is not None:
            (root / "result.json").write_text(json.dumps(result), encoding="utf-8")
        summary = Path(tmp) / "summary.md"
        env = {**os.environ, "RUNNER_TEMP": tmp, "GITHUB_STEP_SUMMARY": str(summary)}
        done = subprocess.run([sys.executable, "-I", "-c", _embedded_python()], env=env,
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr
        return summary.read_text(encoding="utf-8") if summary.exists() else ""


BASE = {"status": "persisted", "reason_code": "exact-canonical-readback-confirmed", "write_attempts": 1,
        "readback_verified": True, "page_id": "page", "revision": "rev"}


class SummaryStepTests(unittest.TestCase):
    def test_step_is_unprivileged_and_unchanged_in_shape(self):
        step = _step()
        self.assertEqual(step["if"], "${{ always() }}")
        self.assertNotIn("env", step)
        self.assertNotIn("NOTION_TOKEN", step["run"])
        self.assertNotIn("secrets.", step["run"])

    def test_prerequisites_are_exposed_when_present(self):
        text = render({**BASE, "activation_prerequisites": {
            "required_fields_present": False,
            "missing_owner_activation": ["Status", "Surface Before Work?"],
            "missing_reviewed_metadata": ["Area", "Learning Type", "Source Link"]}})
        self.assertIn("required_fields_present: `False`", text)
        self.assertIn("missing_owner_activation: `['Status', 'Surface Before Work?']`", text)
        self.assertIn("missing_reviewed_metadata: `['Area', 'Learning Type', 'Source Link']`", text)
        self.assertIn("Agent OS Lessons Learned: persisted", text)
        self.assertIn("readback_verified: `True`", text)

    def test_present_and_complete_prerequisites_report_true_with_empty_lists(self):
        text = render({**BASE, "activation_prerequisites": {
            "required_fields_present": True, "missing_owner_activation": [], "missing_reviewed_metadata": []}})
        self.assertIn("required_fields_present: `True`", text)
        self.assertIn("missing_owner_activation: `[]`", text)

    def test_results_without_prerequisites_add_nothing(self):
        for result in ({**BASE, "activation_prerequisites": None}, BASE, {"status": "blocked"}):
            with self.subTest(result=result):
                text = render(result)
                self.assertNotIn("required_fields_present", text)
                self.assertNotIn("missing_owner_activation", text)
        self.assertIn("Agent OS Lessons Learned: unavailable", render(None))

    def test_hostile_or_unbounded_values_are_not_echoed(self):
        secret = "ntn_" + "S" * 40
        text = render({**BASE, "activation_prerequisites": {
            "required_fields_present": secret,
            "missing_owner_activation": [secret, {"raw": "notion payload"}, "Status"] + ["Area"] * 1000,
            "missing_reviewed_metadata": "Area" * 5000}})
        self.assertNotIn(secret, text)
        self.assertNotIn("notion payload", text)
        self.assertIn("required_fields_present: `False`", text)
        self.assertIn("missing_reviewed_metadata: `[]`", text)
        line = next(item for item in text.splitlines() if item.startswith("missing_owner_activation"))
        self.assertLessEqual(line.count("Area") + line.count("Status"), 5)
        self.assertLess(len(text), 1200)

    def test_malformed_prerequisite_shapes_never_crash_the_always_run_step(self):
        for value in ([], "x", 7, {"missing_owner_activation": 3}, {"missing_reviewed_metadata": None}):
            with self.subTest(value=value):
                render({**BASE, "activation_prerequisites": value})


if __name__ == "__main__":
    unittest.main()
