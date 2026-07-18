from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "04_Registry" / "reusable-capabilities.yml"
REQUIRED_FIELDS = {
    "capability_id",
    "name",
    "summary",
    "status",
    "canonical_paths",
    "public_interfaces",
    "owner_agent",
    "known_consumers",
    "tests",
    "keywords",
    "reuse_guidance",
    "side_effects",
}
EXPECTED_IDS = {
    "issue-acceptance-report",
    "issue-readiness-evaluator",
    "issue-label-checker",
    "readonly-connector-contract",
    "navigation-index-reader",
}
SAFE_PACKAGE_INTERFACES = {
    "scripts.agent_os_issue_acceptance:render_report",
    "scripts.agent_os_issue_acceptance:ReadinessOutcome",
    "scripts.agent_os_issue_acceptance:ReadinessResult",
    "scripts.agent_os_issue_acceptance:evaluate_issue_readiness",
    "scripts.agent_os_issue_labels:evaluate_issue_labels",
}


def _load_registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _defined_or_exported_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            symbols.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            symbols.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
    return symbols


def _module_candidates(module_name: str, canonical_paths: list[str]) -> list[Path]:
    module_suffix = Path(*module_name.split(".")).with_suffix(".py")
    init_suffix = Path(*module_name.split(".")) / "__init__.py"
    return [
        ROOT / relative_path
        for relative_path in canonical_paths
        if Path(relative_path).as_posix().endswith(module_suffix.as_posix())
        or Path(relative_path).as_posix().endswith(init_suffix.as_posix())
    ]


def test_registry_shape_and_seed_count() -> None:
    registry = _load_registry()
    capabilities = registry["capabilities"]

    assert registry["registry_version"] == "0.1.0"
    assert len(capabilities) == 5
    assert {record["capability_id"] for record in capabilities} == EXPECTED_IDS
    assert all(record["status"] == "active" for record in capabilities)


def test_required_fields_identifiers_and_consumer_evidence() -> None:
    for record in _load_registry()["capabilities"]:
        assert REQUIRED_FIELDS <= record.keys()
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", record["capability_id"])
        for field in REQUIRED_FIELDS - {"known_consumers"}:
            assert record[field], f"{record['capability_id']} has empty required field {field}"
        assert record["known_consumers"] or record.get("known_consumer_exemption")


def test_canonical_and_test_paths_exist() -> None:
    for record in _load_registry()["capabilities"]:
        for field in ("canonical_paths", "tests"):
            for relative_path in record[field]:
                assert (ROOT / relative_path).exists(), (
                    f"{record['capability_id']} references missing {field} path: {relative_path}"
                )


def test_public_interfaces_have_valid_format_and_static_symbols() -> None:
    for record in _load_registry()["capabilities"]:
        for interface in record["public_interfaces"]:
            assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*", interface)
            module_name, symbol_name = interface.split(":", 1)
            candidates = _module_candidates(module_name, record["canonical_paths"])
            assert candidates, f"No canonical source file found for {interface}"
            assert any(symbol_name in _defined_or_exported_symbols(path) for path in candidates), (
                f"Static symbol {symbol_name} not found for {interface}"
            )


def test_existing_package_exports_are_safe_to_import() -> None:
    for interface in SAFE_PACKAGE_INTERFACES:
        module_name, symbol_name = interface.split(":", 1)
        module = importlib.import_module(module_name)
        assert hasattr(module, symbol_name)
