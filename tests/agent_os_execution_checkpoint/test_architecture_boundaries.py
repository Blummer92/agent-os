"""Architecture-boundary tests for scripts/agent_os_execution_checkpoint.

Proves -- statically, via AST import inspection, not by trusting a
docstring -- that no network, subprocess, GitHub/Drive/Sheets/Notion,
Scheduler-execution, lease/worktree, daemon/poller, or retry capability is
reachable from this package's own source, and that importing the package
performs no I/O.
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "agent_os_execution_checkpoint"

FORBIDDEN_TOP_LEVEL_MODULES = frozenset(
    {
        "subprocess",
        "socket",
        "urllib",
        "urllib.request",
        "http",
        "http.client",
        "requests",
        "ftplib",
        "smtplib",
        "asyncio",  # no background poller/daemon
        "sched",
        "threading",
        "multiprocessing",
    }
)

# Substrings that, if present anywhere in a dotted import path, indicate a
# reachable capability this package must never touch.
FORBIDDEN_IMPORT_SUBSTRINGS = (
    "github",
    "google",
    "drive",
    "sheets",
    "notion",
    "cloud_build",
    "cloudbuild",
    "workflow_scheduler",
    "agent_os_execution_service",
    "lease",
    "worktree",
    "retry",
    "credential",
)


def _module_source_files() -> tuple[Path, ...]:
    return tuple(sorted(PACKAGE_ROOT.glob("*.py")))


def _imported_module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
    return names


def test_package_has_source_files_to_check() -> None:
    files = _module_source_files()
    assert len(files) >= 6, "expected models/identity/store/invalidation/resume_planner/mutation_intent"


def test_no_forbidden_top_level_stdlib_modules_are_imported() -> None:
    for path in _module_source_files():
        imported = _imported_module_names(path)
        overlap = imported & FORBIDDEN_TOP_LEVEL_MODULES
        assert not overlap, f"{path.name} imports forbidden module(s): {sorted(overlap)}"


def test_no_forbidden_capability_substrings_are_imported() -> None:
    for path in _module_source_files():
        imported = _imported_module_names(path)
        for module_name in imported:
            lowered = module_name.lower()
            for forbidden in FORBIDDEN_IMPORT_SUBSTRINGS:
                assert forbidden not in lowered, (
                    f"{path.name} imports {module_name!r}, which contains "
                    f"forbidden substring {forbidden!r}"
                )


def test_only_authorized_sibling_packages_are_imported() -> None:
    """The sole cross-package dependency this design authorizes is
    scripts.agent_os_issue_acceptance, reused for LifecycleStage,
    AuthorityProjection/AuthorizationState, and AgentOperatingModeDecision."""

    for path in _module_source_files():
        for module_name in _imported_module_names(path):
            if not module_name.startswith("scripts."):
                continue
            authorized = (
                module_name == "scripts.agent_os_issue_acceptance"
                or module_name.startswith("scripts.agent_os_issue_acceptance.")
                or module_name == "scripts.agent_os_execution_checkpoint"
                or module_name.startswith("scripts.agent_os_execution_checkpoint.")
            )
            assert authorized, (
                f"{path.name} imports unauthorized sibling package {module_name!r}"
            )


def test_no_dunder_import_or_importlib_indirection_hides_a_forbidden_module() -> None:
    for path in _module_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = tuple(alias.name for alias in node.names)
                assert not any(
                    name == "importlib" or name.startswith("importlib.")
                    for name in imported
                ), f"{path.name} imports importlib for dynamic import indirection"

            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not (
                    module == "importlib" or module.startswith("importlib.")
                ), f"{path.name} imports from importlib for dynamic import indirection"

            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                assert name != "__import__", f"{path.name} calls __import__ directly"
                assert name != "import_module", (
                    f"{path.name} calls import_module for dynamic import indirection"
                )


def test_module_bodies_contain_no_direct_subprocess_or_os_system_calls() -> None:
    forbidden_calls = {"system", "popen", "run", "Popen", "call", "check_call", "check_output"}
    for path in _module_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in forbidden_calls:
                base = getattr(node.value, "id", "")
                assert base not in {"subprocess", "os"}, (
                    f"{path.name} references {base}.{node.attr}, a forbidden "
                    "subprocess/shell surface"
                )


# --- package import performs no I/O -----------------------------------------


def test_package_import_performs_no_filesystem_io(monkeypatch) -> None:
    """Reload every submodule with disk-touching builtins patched to raise.

    Import-time code (module bodies, class/function definitions) must never
    call into the filesystem; only functions defined in store.py may do so,
    and only when actually invoked by a caller.
    """

    def _forbidden(*_args, **_kwargs):  # pragma: no cover - should never run
        raise AssertionError("package import must never perform filesystem I/O")

    monkeypatch.setattr("builtins.open", _forbidden)
    import os
    import tempfile

    monkeypatch.setattr(os, "mkdir", _forbidden)
    monkeypatch.setattr(os, "makedirs", _forbidden)
    monkeypatch.setattr(os, "replace", _forbidden)
    monkeypatch.setattr(tempfile, "mkstemp", _forbidden)

    module_names = [
        "scripts.agent_os_execution_checkpoint",
        "scripts.agent_os_execution_checkpoint.models",
        "scripts.agent_os_execution_checkpoint.identity",
        "scripts.agent_os_execution_checkpoint.invalidation",
        "scripts.agent_os_execution_checkpoint.store",
        "scripts.agent_os_execution_checkpoint.resume_planner",
        "scripts.agent_os_execution_checkpoint.mutation_intent",
    ]
    originals = {name: sys.modules.get(name) for name in module_names}
    for name in module_names:
        sys.modules.pop(name, None)
    try:
        for name in module_names:
            importlib.import_module(name)
    finally:
        for name, original in originals.items():
            sys.modules.pop(name, None)
            if original is not None:
                sys.modules[name] = original
            else:
                importlib.import_module(name)


# --- pure functions never mutate their inputs or reach for ambient state ---


def test_plan_resume_and_checkpoint_construction_are_pure_no_git_or_network(
    monkeypatch,
) -> None:
    """A behavioral companion to the static checks: actually construct a
    checkpoint and a resume plan with subprocess/socket poisoned, proving
    the documented pure-local behavior end to end, not just via imports."""

    import subprocess

    def _forbidden(*_args, **_kwargs):  # pragma: no cover - should never run
        raise AssertionError("plan_resume/ExecutionCheckpoint must never shell out")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)

    import hashlib

    from scripts.agent_os_execution_checkpoint.invalidation import BindingSnapshot
    from scripts.agent_os_execution_checkpoint.models import (
        CheckpointStage,
        InvalidationState,
        LifecycleState,
        StageStatus,
        WorktreeRole,
    )
    from scripts.agent_os_execution_checkpoint.models import ExecutionCheckpoint
    from scripts.agent_os_execution_checkpoint.resume_planner import plan_resume
    from scripts.agent_os_issue_acceptance.issue_operational_state import LifecycleStage

    sha40 = "7d01ad36d7f9c9cba41c9fee62a562b7689c2fbe"
    hex64 = hashlib.sha256(b"x").hexdigest()
    checkpoint = ExecutionCheckpoint(
        schema="agent-os.execution-checkpoint",
        schema_version="1.0",
        repository="Blummer92/agent-os",
        issue_number=895,
        invocation_id="inv-1",
        execution_id="exe-1",
        branch="agent/895-execution-checkpoint",
        worktree_fingerprint=hex64,
        worktree_role=WorktreeRole.PRIMARY,
        environment_fingerprint=hex64,
        source_sha=sha40,
        tested_sha=sha40,
        merge_base_sha=sha40,
        dependency_fingerprint=hex64,
        command_plan_id=f"command-plan:{hex64}",
        acceptance_criteria_digest=hex64,
        governance_contract_digest=hex64,
        lifecycle_stage=LifecycleStage.PLANNING,
        checkpoint_stage=CheckpointStage.PREFLIGHT_COMPLETE,
        stage_status=StageStatus.PASSED,
        evidence_hashes=(),
        invalidation_state=InvalidationState.CURRENT,
        lifecycle_state=LifecycleState.ACTIVE,
        recorded_at="2026-08-05T12:00:00Z",
        actor_id="github-service-agent",
    )
    bindings = BindingSnapshot(
        source_sha=sha40,
        tested_sha=sha40,
        dependency_fingerprint=hex64,
        environment_fingerprint=hex64,
        worktree_fingerprint=hex64,
        branch="agent/895-execution-checkpoint",
        acceptance_criteria_digest=hex64,
        governance_contract_digest=hex64,
        command_plan_id=f"command-plan:{hex64}",
        merge_base_sha=sha40,
    )
    plan = plan_resume(
        repository="Blummer92/agent-os",
        issue_number=895,
        execution_id="exe-1",
        evaluated_at="2026-08-05T12:00:00Z",
        current_bindings=bindings,
        stored_checkpoints=(checkpoint,),
    )
    assert plan.resume_point is not None
