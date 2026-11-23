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
import sys
import types
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
    _assert_retired_not_importable(name)


def _assert_retired_not_importable(name: str) -> None:
    """Fail closed if a retired package is loaded or findable.

    ``importlib.util.find_spec`` raises ``ValueError`` when the module is
    already in ``sys.modules`` with ``__spec__ is None``. Treating that as
    "absent" would let a preloaded deleted module pass this guard, so a
    loaded entry fails first and a ``ValueError`` fails instead of passing.
    The filesystem path check above is the separate protection against a
    reintroduced retired file; this check covers the live-import state.
    This guard is test-only: no production code consults it, so a failure
    here is a test defect signal, not a production authorization bypass.
    """
    loaded = [mod for mod in sys.modules if mod == name or mod.startswith(name + ".")]
    assert not loaded, f"retired package still loaded: {name} -> {loaded}"
    try:
        spec = importlib.util.find_spec(name)
    except ImportError:
        return  # Genuinely not findable from this environment == absent.
    except ValueError as exc:
        raise AssertionError(
            f"retired package import state is ambiguous (find_spec ValueError): {name}: {exc}"
        ) from exc
    assert spec is None, f"retired package still importable: {name}"


def test_preloaded_deleted_module_with_no_spec_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control: a deleted module preloaded with ``__spec__ is None``
    makes ``find_spec`` raise ``ValueError``; the old guard swallowed that
    as "absent" and passed while the module was live in ``sys.modules``."""
    stub = types.ModuleType("scripts.agent_os_validation_failures")
    stub.__spec__ = None
    monkeypatch.setitem(sys.modules, "scripts.agent_os_validation_failures", stub)
    with pytest.raises(AssertionError, match="still loaded"):
        _assert_retired_not_importable("scripts.agent_os_validation_failures")


def test_find_spec_value_error_is_not_treated_as_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control: any ``ValueError`` from ``find_spec`` must fail the
    guard, never silently count as "absent"."""
    real_find_spec = importlib.util.find_spec

    def _raising_find_spec(name: str, *args: object, **kwargs: object) -> object:
        if name == "scripts.agent_os_validation_failures":
            raise ValueError("scripts.agent_os_validation_failures.__spec__ is None")
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", _raising_find_spec)
    with pytest.raises(AssertionError, match="ambiguous"):
        _assert_retired_not_importable("scripts.agent_os_validation_failures")


def test_neighbouring_canonical_modules_still_import() -> None:
    from scripts.agent_os_issue_acceptance import (
        validation_failure_classifier,
    )
    from scripts.agent_os_notion_read_request import admission

    assert validation_failure_classifier is not None
    assert admission is not None
