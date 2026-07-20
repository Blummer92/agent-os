from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "07_Agent_Tests/validate_registry_consistency.py"
SPEC = importlib.util.spec_from_file_location("registry_consistency", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def baseline(tmp_path: Path) -> Path:
    write(tmp_path, "04_Registry/agent-inheritance-registry.md", """# Agent Inheritance Registry

| Agent | Inherits | Overlay |
|---|---|---|
| Integration Manager | Global | `integration-manager` |
| QA / Test Agent | Global | qa-test-agent |

## Routed Combinations

| Workflow | Canonical Owner | Overlays |
|---|---|---|
| Example | Integration Manager | selected registered owner |
""")
    write(tmp_path, "04_Registry/responsibility-matrix.md", """# Responsibility Matrix

| Responsibility | Primary | Support |
|---|---|---|
| Navigation Registry governance and lookup routing | Integration Manager | QA / Test Agent |
""")
    write(tmp_path, "02_Agent_Overlays/integration-manager.md", "`01_Shared_Standards/navigation/navigation-registry-standard.md`\n")
    write(tmp_path, "02_Agent_Overlays/qa-test-agent.md", "# QA\n")
    write(tmp_path, "07_Agent_Tests/integration-manager.tests.md", "# Tests\n")
    write(tmp_path, "07_Agent_Tests/qa-test-agent.tests.md", "# Tests\n")
    write(tmp_path, "01_Shared_Standards/navigation/navigation-registry-standard.md", "# Standard\n")
    return tmp_path


def replace_matrix_support(root: Path, value: str) -> None:
    matrix = root / "04_Registry/responsibility-matrix.md"
    matrix.write_text(
        matrix.read_text(encoding="utf-8").replace("QA / Test Agent", value),
        encoding="utf-8",
    )


def append_matrix_row(root: Path, row: str) -> None:
    matrix = root / "04_Registry/responsibility-matrix.md"
    matrix.write_text(matrix.read_text(encoding="utf-8") + row, encoding="utf-8")


def errors_with_support(root: Path, value: str) -> list[str]:
    replace_matrix_support(root, value)
    return MODULE.validate(root)


def test_current_repository_passes() -> None:
    assert MODULE.validate(MODULE.ROOT) == []


def test_clean_baseline_passes(tmp_path: Path) -> None:
    assert MODULE.validate(baseline(tmp_path)) == []


def test_output_is_deterministic_and_non_mutating(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    first = MODULE.validate(root)
    second = MODULE.validate(root)
    after = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert first == second == []
    assert before == after


def test_missing_overlay_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    (root / "02_Agent_Overlays/qa-test-agent.md").unlink()
    assert "Registered agent has no overlay: qa-test-agent" in MODULE.validate(root)


def test_missing_test_file_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    (root / "07_Agent_Tests/qa-test-agent.tests.md").unlink()
    assert "Registered agent has no test file: qa-test-agent" in MODULE.validate(root)


def test_unknown_matrix_agent_fails_and_does_not_count_as_coverage(tmp_path: Path) -> None:
    errors = errors_with_support(baseline(tmp_path), "Unknown Agent")
    assert any("Unknown support value" in error for error in errors)
    assert "Canonical agent has no Responsibility Matrix assignment: QA / Test Agent" in errors


def test_routing_placeholder_is_not_valid_matrix_support_or_coverage(tmp_path: Path) -> None:
    errors = errors_with_support(baseline(tmp_path), "selected registered owner")
    assert any("Unknown support value" in error for error in errors)
    assert "Canonical agent has no Responsibility Matrix assignment: QA / Test Agent" in errors


def test_exact_helper_support_surface_is_valid_but_not_agent_coverage(tmp_path: Path) -> None:
    errors = errors_with_support(baseline(tmp_path), "Python Development Overlay")
    assert not any("Unknown support value" in error for error in errors)
    assert "Canonical agent has no Responsibility Matrix assignment: QA / Test Agent" in errors


def test_near_match_helper_support_surface_fails_and_is_not_coverage(tmp_path: Path) -> None:
    errors = errors_with_support(baseline(tmp_path), "Python Development")
    assert any("Unknown support value" in error for error in errors)
    assert "Canonical agent has no Responsibility Matrix assignment: QA / Test Agent" in errors


def test_legacy_alias_is_not_agent_coverage(tmp_path: Path) -> None:
    errors = errors_with_support(baseline(tmp_path), "QA Agent")
    assert any("Unknown support value" in error for error in errors)
    assert "Canonical agent has no Responsibility Matrix assignment: QA / Test Agent" in errors


def test_primary_assignment_counts_as_coverage(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_matrix_support(root, "Python Development Overlay")
    append_matrix_row(root, "| Validation evidence | QA / Test Agent | Integration Manager |\n")
    assert MODULE.validate(root) == []


def test_exact_canonical_support_assignment_counts_as_coverage(tmp_path: Path) -> None:
    assert MODULE.validate(baseline(tmp_path)) == []


def test_registered_agent_without_any_matrix_assignment_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    registry = root / "04_Registry/agent-inheritance-registry.md"
    registry.write_text(
        registry.read_text(encoding="utf-8").replace(
            "| QA / Test Agent | Global | qa-test-agent |",
            "| QA / Test Agent | Global | qa-test-agent |\n| Agent Orchestrator | Global | agent-orchestrator |",
        ),
        encoding="utf-8",
    )
    write(root, "02_Agent_Overlays/agent-orchestrator.md", "# Agent Orchestrator\n")
    write(root, "07_Agent_Tests/agent-orchestrator.tests.md", "# Tests\n")
    assert "Canonical agent has no Responsibility Matrix assignment: Agent Orchestrator" in MODULE.validate(root)


def test_malformed_or_empty_matrix_row_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    append_matrix_row(root, "| Empty support | Integration Manager | |\n")
    assert "Responsibility Matrix contains a malformed or empty row" in MODULE.validate(root)


def test_missing_shared_standard_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    (root / "01_Shared_Standards/navigation/navigation-registry-standard.md").unlink()
    assert any("Overlay references missing path" in error for error in MODULE.validate(root))


def test_navigation_owner_mismatch_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    matrix = root / "04_Registry/responsibility-matrix.md"
    matrix.write_text(matrix.read_text(encoding="utf-8").replace("Integration Manager", "QA / Test Agent", 1), encoding="utf-8")
    assert "Navigation Registry primary owner must be Integration Manager" in MODULE.validate(root)


def test_navigation_description_can_change_without_failure(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    matrix = root / "04_Registry/responsibility-matrix.md"
    matrix.write_text(matrix.read_text(encoding="utf-8").replace("governance and lookup routing", "cross-system routing and governance"), encoding="utf-8")
    assert MODULE.validate(root) == []


def test_unregistered_overlay_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    write(root, "02_Agent_Overlays/unregistered.md", "# Unregistered\n")
    assert "Overlay is not registered or exempt: unregistered" in MODULE.validate(root)
