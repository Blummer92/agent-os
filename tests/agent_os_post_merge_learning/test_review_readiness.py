"""Regression controls for the exact run link and nonempty CI execution."""
import io
from pathlib import Path
import sys
import tempfile

import yaml

from report_fixtures import REPO, SHA, VALIDATION, ReportCase, commit, repo_root, run
from scripts.agent_os_post_merge_learning.report import build_report


class ReviewReadinessTests(ReportCase):
    def test_link_is_canonical_for_verified_run_not_provider_display_url(self):
        for supplied_url in (f"https://github.com/{REPO}/actions/runs/999", None):
            with self.subTest(url=supplied_url):
                reader = self.reader([commit(1, "docs(api): note")],
                                     validation={**run(), "html_url": supplied_url})
                result = build_report(reader, SHA, 4101, 100)
                self.assertEqual(result["validation"], {
                    "state": "success", "run_url": f"https://github.com/{REPO}{VALIDATION}",
                })
                self.assertEqual(reader.requests.count(VALIDATION), 1)

    def test_both_workflow_jobs_use_same_count_checked_runner(self):
        path = repo_root() / ".github/workflows/agent-os-post-merge-learning.yml"
        jobs = yaml.load(path.read_text(), Loader=yaml.BaseLoader)["jobs"]
        for job, name in (("premerge_tests", "Run exact PR revision regression suite"),
                          ("review", "Positive and hard-negative tests")):
            with self.subTest(job=job):
                step = next(s for s in jobs[job]["steps"] if s.get("name") == name)
                self.assertEqual(step["run"], "python tests/agent_os_post_merge_learning/run_suite.py")

    def test_runner_refuses_empty_all_skipped_and_failing_suites(self):
        from run_suite import run_suite

        for body, code in (
            ("", 5),
            ("    @unittest.skip('control')\n    def test_case(self): pass\n", 5),
            ("    def test_case(self): self.fail('control')\n", 1),
            ("    def test_case(self): pass\n", 0),
            (
                "    def test_run(self): pass\n"
                "    @unittest.skip('control')\n    def test_skip(self): pass\n",
                0,
            ),
        ):
            with self.subTest(code=code, body=body), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)
                if body:
                    (path / "test_runner_control.py").write_text(
                        "import unittest\nclass Control(unittest.TestCase):\n" + body, encoding="utf-8"
                    )
                try:
                    self.assertEqual(run_suite(path, stream=io.StringIO()), code)
                finally:
                    # Discovery imports modules by basename.
                    sys.modules.pop("test_runner_control", None)
