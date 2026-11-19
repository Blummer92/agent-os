"""D06 read-only mutation differentials for overlapping import-boundary tests.

This harness executes the existing detector functions against synthetic import
texts in a temporary file. It does not patch production modules or delete tests.
The passing matrix measures distinctive detection; the fail-first guard records
a suspected missing negative in the single-issue-runtime boundary.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).resolve().parent

DETECTORS = {
    "posix": (
        "test_posix_process_adapter.py",
        "test_module_imports_no_retry_worktree_lease_persistence_or_network_authority",
    ),
    "quarantine": (
        "test_quarantine_review.py",
        "test_module_imports_no_execution_persistence_or_network_authority",
    ),
    "runtime": (
        "test_single_issue_runtime.py",
        "test_module_imports_no_execution_persistence_or_network_authority",
    ),
}


def _original_detector(name: str, mutated_path: Path):
    """Compile the real checked-in assertion, with only its source path replaced."""
    filename, test_name = DETECTORS[name]
    source_path = TEST_DIR / filename
    parsed = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    variables = {"ast": ast, "MODULE_PATH": mutated_path}
    detector = None
    for node in parsed.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name)
                and target.id in {"_FORBIDDEN_IMPORT_ROOTS", "_FORBIDDEN_MODULE_SUBSTRINGS"}
                for target in node.targets
            ):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        variables[target.id] = ast.literal_eval(node.value)
        elif isinstance(node, ast.FunctionDef) and node.name == test_name:
            detector = node
    assert detector is not None, f"original D06 detector missing: {source_path}:{test_name}"
    assert "_FORBIDDEN_IMPORT_ROOTS" in variables
    assert "_FORBIDDEN_MODULE_SUBSTRINGS" in variables
    program = ast.fix_missing_locations(ast.Module(body=[detector], type_ignores=[]))
    exec(compile(program, str(source_path), "exec"), variables)
    return variables[test_name]


@pytest.mark.parametrize(
    ("source", "rejected"),
    [
        ("import math\n", frozenset()),
        ("import socket\n", frozenset(DETECTORS)),
        (
            "import workflow_scheduler.execution.quarantine_review\n",
            frozenset({"posix"}),
        ),
        (
            "import workflow_scheduler.execution.single_issue_runtime\n",
            frozenset({"quarantine"}),
        ),
        (
            "import workflow_scheduler.execution.executor\n",
            frozenset({"posix", "quarantine"}),
        ),
    ],
    ids=[
        "negative-control-safe-import",
        "common-network-prohibition",
        "posix-only-review-import",
        "quarantine-only-runtime-import",
        "runtime-executor-gap-probe",
    ],
)
def test_d06_real_detector_functions_have_distinct_kill_vectors(tmp_path, source, rejected):
    candidate = tmp_path / "synthetic_module.py"
    candidate.write_text(source, encoding="utf-8")
    for name in DETECTORS:
        check = _original_detector(name, candidate)
        if name in rejected:
            with pytest.raises(AssertionError):
                check()
        else:
            check()


def test_d06_runtime_guard_must_reject_direct_executor_import(tmp_path):
    """Fail-first candidate: '.executor.py' cannot match a Python import name."""
    candidate = tmp_path / "synthetic_module.py"
    candidate.write_text(
        "import workflow_scheduler.execution.executor\n", encoding="utf-8"
    )
    check = _original_detector("runtime", candidate)
    with pytest.raises(AssertionError, match="forbidden import"):
        check()
