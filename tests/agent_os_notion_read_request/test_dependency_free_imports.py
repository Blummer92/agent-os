"""Regression coverage for #2902's dependency-free Notion-read import boundary."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).parents[2]


def test_notion_read_imports_do_not_load_unrelated_optional_adapters() -> None:
    """Mirror the hosted admission runner without PyGithub or PyYAML."""
    code = r"""
import importlib.abc
import sys


class _BlockOptionalDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in {"github", "yaml"}:
            raise ModuleNotFoundError(
                f"blocked optional dependency during #2902 regression: {fullname}"
            )
        return None


sys.meta_path.insert(0, _BlockOptionalDependencies())

import workflow_scheduler.governance.github_issue_comment_ingress
import scripts.agent_os_notion_read_request
import scripts.agent_os_notion_read_request.admission
import scripts.agent_os_notion_read_request.runner

for module_name in (
    "workflow_scheduler.adapters.github_pr_comment_adapter",
    "workflow_scheduler.adapters.github_pr_label_adapter",
    "workflow_scheduler.adapters.github_ruleset_admin_adapter",
):
    assert module_name not in sys.modules, module_name
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        (
            str(ROOT / "src"),
            str(ROOT / "08_Tooling" / "workflow-scheduler" / "src"),
            str(ROOT),
        )
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        "dependency-free Notion-read imports failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
