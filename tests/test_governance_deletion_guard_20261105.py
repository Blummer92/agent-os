"""Negative controls for the 2026-11-05 governance two-module deletion.

Retired 2026-11-05 (base main 7f293b59):
- scripts/agent_os_validation_failures (390 prod lines)
- scripts/agent_os_notion_curriculum_preflight (1345 prod .py lines + 74-line README)

Both had zero production importers; only their own test files referenced
them. These controls pin the deletion and prove the neighbouring canonical
modules that stay were not collateral damage.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

DELETED_PATHS = [
    "scripts/agent_os_validation_failures",
    "tests/agent_os_validation_failures",
    "scripts/agent_os_notion_curriculum_preflight",
    "tests/agent_os_notion_curriculum_preflight",
    "tests/fixtures/agent_os_notion_curriculum_preflight",
]

DELETED_IMPORTS = [
    "scripts.agent_os_validation_failures",
    "scripts.agent_os_notion_curriculum_preflight",
]


@pytest.mark.parametrize("rel", DELETED_PATHS)
def test_retired_package_path_is_absent(rel: str) -> None:
    assert not (REPO_ROOT / rel).exists(), f"retired path still present: {rel}"


@pytest.mark.parametrize("name", DELETED_IMPORTS)
def test_retired_package_is_not_importable(name: str) -> None:
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return  # Not importable from this environment == absent.
    assert spec is None, f"retired package still importable: {name}"


def test_neighbouring_canonical_modules_still_import() -> None:
    from scripts.agent_os_issue_acceptance import (
        validation_failure_classifier,
    )
    from scripts.agent_os_notion_read_request import admission

    assert validation_failure_classifier is not None
    assert admission is not None
