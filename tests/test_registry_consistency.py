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
    target.write_text(text)


def baseline(tmp_path: Path) -> Path:
    write(
        tmp_path,
        "04_Registry/agent-inheritance-registry.md",
        """# Agent Inheritance Registry

| Agent | Inherits | Overlay |
|---|---|---|
| Integration Manager | Global | integration-manager |
| QA / Test Agent | Global | qa-test-agent |

## Routed Combinations
""",
    )
    write(
        tmp_path,
        "04_Registry/responsibility-matrix.md",
        """# Responsibility Matrix

| Responsibility | Primary | Support |
|---|---|---|
| Navigation Registry governance and lookup routing | Integration Manager | QA / Test Agent |
""",
    )
    write(
        tmp_path,
        "02_Agent_Overlays/integration-manager.md",
        "`01_Shared_Standards/navigation/navigation-registry-standard.md`\n",
    )
    write(tmp_path, "02_Agent_Overlays/qa-test-agent.md", "# QA\n")
    write(tmp_path, "07_Agent_Tests/integration-manager.tests.md", "# Tests\n")
    write(tmp_path, "07_Agent_Tests/qa-test-agent.tests.md", "# Tests\n")
    write(
        tmp_path,
        "01_Shared_Standards/navigation/navigation-registry-standard.md",
        "# Standard\n",
    )
    return tmp_path


def test_current_repository_passes() -> None:
    assert MODULE.validate(MODULE.ROOT) == []


def test_clean_baseline_passes(tmp_path: Path) -> None:
    assert MODULE.validate(baseline(tmp_path)) == []


def test_missing_overlay_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    (root / "02_Agent_Overlays/qa-test-agent.md").unlink()
    assert "Registered agent has no overlay: qa-test-agent" in MODULE.validate(root)


def test_missing_test_file_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    (root / "07_Agent_Tests/qa-test-agent.tests.md").unlink()
    assert "Registered agent has no test file: qa-test-agent" in MODULE.validate(root)


def test_unknown_matrix_agent_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    matrix = root / "04_Registry/responsibility-matrix.md"
    matrix.write_text(matrix.read_text().replace("QA / Test Agent", "Unknown Agent"))
    assert any("Unknown support value" in error for error in MODULE.validate(root))


def test_missing_shared_standard_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    standard = root / "01_Shared_Standards/navigation/navigation-registry-standard.md"
    standard.unlink()
    assert any("Overlay references missing path" in error for error in MODULE.validate(root))


def test_navigation_owner_mismatch_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    matrix = root / "04_Registry/responsibility-matrix.md"
    matrix.write_text(matrix.read_text().replace("Integration Manager", "QA / Test Agent", 1))
    assert "Navigation Registry primary owner must be Integration Manager" in MODULE.validate(root)


def test_unregistered_overlay_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    write(root, "02_Agent_Overlays/unregistered.md", "# Unregistered\n")
    assert "Overlay is not registered or exempt: unregistered" in MODULE.validate(root)
