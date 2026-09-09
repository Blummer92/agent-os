from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

GOVERNED_CONTINUATION_DECISIONS = {
    "plan_execution_continuation": REPO_ROOT / "08_Tooling/workflow-scheduler/src/workflow_scheduler/execution/continuation.py",
    "plan_red_ci_continuation": REPO_ROOT / "08_Tooling/workflow-scheduler/src/workflow_scheduler/execution/red_ci_continuation.py",
    "classify_recovery_progress": REPO_ROOT / "08_Tooling/workflow-scheduler/src/workflow_scheduler/execution/recovery_progress.py",
    "evaluate_mission_completion_admission": REPO_ROOT / "scripts/agent_os_execution_interface/mission_completion_admission.py",
    "evaluate_failed_repair_admission": REPO_ROOT / "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/failed_repair_admission.py",
    "drive_governed_continuation": REPO_ROOT / "scripts/agent_os_execution_interface/continuation_driver.py",
}

PRODUCTION_ROOTS = (
    REPO_ROOT / "scripts",
    REPO_ROOT / "08_Tooling/agent-memory-context-manager/src",
    REPO_ROOT / "08_Tooling/agent-os-execution-service/src",
    REPO_ROOT / "08_Tooling/workflow-scheduler/src",
)


def _production_python_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for root in PRODUCTION_ROOTS:
        files.extend(path for path in root.rglob("*.py") if "tests" not in path.parts)
    return tuple(sorted(set(files)))


def _referenced_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _production_consumers(function_name: str, owner: Path) -> tuple[Path, ...]:
    consumers = []
    for path in _production_python_files():
        if path == owner:
            continue
        if function_name in _referenced_names(path):
            consumers.append(path.relative_to(REPO_ROOT))
    return tuple(consumers)


def test_every_governed_continuation_decision_has_a_production_consumer() -> None:
    missing = {
        name: str(owner.relative_to(REPO_ROOT))
        for name, owner in GOVERNED_CONTINUATION_DECISIONS.items()
        if not _production_consumers(name, owner)
    }
    assert not missing, (
        "Governed continuation decisions must be reachable from production code; "
        f"missing consumers: {missing}"
    )


def test_driver_is_reached_from_a_runtime_entrypoint() -> None:
    consumers = _production_consumers(
        "drive_governed_continuation",
        GOVERNED_CONTINUATION_DECISIONS["drive_governed_continuation"],
    )
    assert Path("scripts/agent_os_execution_interface/hook_adapter.py") in consumers
