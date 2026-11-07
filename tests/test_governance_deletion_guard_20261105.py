"""Negative controls for the 2026-11-05 governance simplification deletions.

Retired 2026-11-05 (base main 7f293b59):
- scripts/agent_os_validation_failures (390 prod lines)
- scripts/agent_os_notion_curriculum_preflight (1345 prod .py lines + 74-line README)
- 08_Tooling/notion-compute-decision-writer (592 prod .py lines + 106-line
  README + 17-line pyproject; Loop 3 governance simplification)
- src/instructional_workflow_contracts/ppux_experiment_evidence.py
  (159 prod lines; Loop 4 governance simplification)
- src/instructional_workflow_contracts/assessment_experiment_evidence.py
  (85 prod lines; Loop 5 governance simplification)
- scripts/agent-os-fast-preflight.py (151 prod lines; Loop 6 governance
  simplification)

Both Loop 1/2 modules had zero production importers; only their own test
files referenced them. The Loop 3 package likewise had zero production
importers, no entry points, no workflow/registry references, and no live
Notion adapter (live mutation was never activated under the #1420 Change
Request). The Loop 4 adapter likewise had zero production importers, was not
exported from the package __init__, and had no docs/registry/workflow/
packaging/dynamic references; only its own test file referenced it. The
Loop 5 adapter has the identical profile; its only additional wrinkle is
that its test fixtures are shared with the #846 standard test, so the
fixtures stay and that test stays green.

These controls pin the deletion and prove the neighbouring
canonical modules that stay were not collateral damage.
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
    "08_Tooling/notion-compute-decision-writer",
    "src/instructional_workflow_contracts/ppux_experiment_evidence.py",
    "tests/test_ppux_experiment_evidence.py",
    "src/instructional_workflow_contracts/assessment_experiment_evidence.py",
    "tests/test_assessment_experiment_evidence.py",
    "scripts/agent-os-fast-preflight.py",
    "tests/agent_os_remote_validation/test_fast_preflight.py",
]

DELETED_IMPORTS = [
    "scripts.agent_os_validation_failures",
    "scripts.agent_os_notion_curriculum_preflight",
    "notion_compute_decision_writer",
    "src.instructional_workflow_contracts.ppux_experiment_evidence",
    "src.instructional_workflow_contracts.assessment_experiment_evidence",
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
    if spec is None:
        return
    # `scripts/` is a namespace package spanning all of sys.path, so a stale
    # copy in an unrelated checkout (e.g. an older worktree on sys.path)
    # must not fail this test. Only a spec resolving under THIS repo root
    # proves the retired package is still importable here.
    locations = [getattr(spec, "origin", None)] + list(
        getattr(spec, "submodule_search_locations", None) or []
    )
    in_repo = [
        loc
        for loc in locations
        if loc is not None and Path(loc).is_relative_to(REPO_ROOT)
    ]
    assert not in_repo, f"retired package still importable from repo: {name} -> {in_repo}"


def test_neighbouring_canonical_modules_still_import() -> None:
    from scripts.agent_os_issue_acceptance import (
        validation_failure_classifier,
    )
    from scripts.agent_os_notion_read_request import admission

    assert validation_failure_classifier is not None
    assert admission is not None


def test_loop3_neighbouring_canonical_modules_still_import() -> None:
    # Loop 3 neighbour check: the #1419 projection producer that the deleted
    # #1424 writer consumed by schema reference only (never by import) stays,
    # as does the sibling operational-guidance writer, which writes a
    # different field on the same Notion destination and is NOT a replacement
    # for the deleted Compute Decision writer (no replacement exists).
    import sys

    sys.path.insert(
        0,
        str(
            REPO_ROOT
            / "08_Tooling/notion-operational-guidance-writer/src"
        ),
    )
    from scripts.agent_os_issue_acceptance import compute_control_projection
    from notion_operational_guidance_writer import writer as guidance_writer

    assert compute_control_projection.ComputeDisposition is not None
    assert compute_control_projection.ComputeControlProjection is not None
    assert guidance_writer is not None
    assert (
        REPO_ROOT / "08_Tooling/notion-operational-guidance-writer"
    ).is_dir()


def test_loop4_neighbouring_canonical_modules_still_import() -> None:
    # Loop 4 neighbour check: the shared EXH experiment-evidence core that
    # the deleted PPUX adapter projected into stays, as does the package
    # public surface (the deleted adapter was never exported from it).
    # NOTE (Loop 5): this function previously also asserted the sibling
    # assessment adapter still imported; that adapter was itself retired in
    # Loop 5, so its assertion moved to the retired-path/import lists above
    # and the Loop 5 neighbour check below.
    from src.instructional_workflow_contracts import (
        experiment_evidence,
    )
    from src.instructional_workflow_contracts import (
        validate_experiment_evidence,
    )

    assert experiment_evidence.CONTRACT_VERSION == "experiment-evidence-v1"
    assert validate_experiment_evidence is not None
    assert (
        REPO_ROOT / "src/instructional_workflow_contracts/experiment_evidence.py"
    ).is_file()


def test_loop5_neighbouring_canonical_modules_still_import() -> None:
    # Loop 5 neighbour check: the shared EXH experiment-evidence core and
    # the sibling adapters that stay (bounded_drive_lookup, exported from
    # the package __init__; contextual_teacher_action, likewise exported)
    # still import, and the package public surface is intact. The #846
    # standard document and its shared cross-unit-portability fixtures also
    # stay: they are consumed by tests/unit/test_assessment_cross_unit_validation.py,
    # which never imported the deleted adapter.
    from src.instructional_workflow_contracts import (
        bounded_drive_lookup,
        contextual_teacher_action,
        experiment_evidence,
    )
    from src.instructional_workflow_contracts import (
        resolve_revision_target,
        validate_contextual_teacher_action,
        validate_experiment_evidence,
    )

    assert experiment_evidence.CONTRACT_VERSION == "experiment-evidence-v1"
    assert validate_experiment_evidence is not None
    assert bounded_drive_lookup.resolve_revision_target is resolve_revision_target
    assert (
        contextual_teacher_action.validate_contextual_teacher_action
        is validate_contextual_teacher_action
    )
    assert (
        REPO_ROOT / "src/instructional_workflow_contracts/experiment_evidence.py"
    ).is_file()
    assert (
        REPO_ROOT
        / "tests/fixtures/assessment_blueprint/cross-unit-portability-positive.json"
    ).is_file()
    assert (
        REPO_ROOT
        / "tests/fixtures/assessment_blueprint/cross-unit-portability-negative.json"
    ).is_file()


def test_loop6_neighbouring_canonical_preflights_still_work() -> None:
    # Loop 6 neighbour check: the deleted fast-preflight was never wired
    # into any live consumer, so the live preflight surfaces that stay are
    # (a) the registered PR-state/exact-head preflight, (b) the live
    # .claude hook entrypoint, and (c) the canonical aggregate runner
    # (validate-all.sh, invoked by agent-os-validation.yml). The deleted
    # script had a hyphenated filename, so it was never importable as a
    # module; its path-absence entries in DELETED_PATHS above are the
    # control (no DELETED_IMPORTS entry applies).
    from scripts.agent_os_pr_remediation.preflight import PreflightResult

    assert PreflightResult is not None
    assert (
        REPO_ROOT / "scripts/agent-os-execution-interface-preflight.py"
    ).is_file()
    assert "agent-os-execution-interface-preflight.py" in (
        REPO_ROOT / ".claude/settings.json"
    ).read_text(encoding="utf-8")
    assert "validate-all.sh" in (
        REPO_ROOT / ".github/workflows/agent-os-validation.yml"
    ).read_text(encoding="utf-8")
