from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "04_Registry" / "reusable-capabilities.yml"
REGISTRY_PACKAGE_SRC = ROOT / "08_Tooling" / "reusable-capability-registry" / "src"
sys.path.insert(0, str(REGISTRY_PACKAGE_SRC))

from reusable_capability_registry.reader import RegistryReader  # noqa: E402

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
APPROVED_CAPABILITY_STATUSES = {
    "approval-applicability-evidence": "experimental",
    "candidate-packet-entrypoint": "experimental",
    "instructional-workflow-contract-core": "active",
    "issue-acceptance-report": "active",
    "issue-batch-graph": "experimental",
    "issue-batch-identity-collision-check": "experimental",
    "issue-batch-planning": "experimental",
    "issue-batch-supplied-graph-scope-checks": "experimental",
    "issue-label-checker": "active",
    "issue-readiness-evaluator": "active",
    "issueplan-current-state-evidence": "active",
    "issueplan-metadata-scanner": "active",
    "navigation-index-reader": "active",
    "ppux-picture-perfect-prompt-projection": "active",
    "pr-review-remediation": "experimental",
    "readonly-connector-contract": "active",
    "scheduler-planning-handoff": "active",
}
SAFE_PACKAGE_INTERFACES = {
    "scripts.agent_os_issue_acceptance:render_report",
    "scripts.agent_os_issue_acceptance:ReadinessOutcome",
    "scripts.agent_os_issue_acceptance:ReadinessResult",
    "scripts.agent_os_issue_acceptance:evaluate_issue_readiness",
    "scripts.agent_os_issue_acceptance:entity_id_collision_check",
    "scripts.agent_os_issue_acceptance:unresolved_dependency_check",
    "scripts.agent_os_issue_acceptance:evaluate_input_scope_coverage",
    "scripts.agent_os_issue_labels:evaluate_issue_labels",
}


def _load_registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


_TS_DECLARED_EXPORT_RE = re.compile(
    r"^export\s+(?:declare\s+)?(?:default\s+)?"
    r"(?:async\s+)?(?:abstract\s+)?"
    r"(?:const|let|var|function|class|type|interface|enum|namespace)\s+"
    r"([A-Za-z_$][A-Za-z0-9_$]*)",
    re.MULTILINE,
)
_TS_EXPORT_CLAUSE_RE = re.compile(r"^export\s*\{([^}]*)\}", re.MULTILINE)


def _typescript_exported_symbols(source: str) -> set[str]:
    """Collect statically declared TypeScript export names.

    This mirrors the Python AST check: a declared interface must really exist in
    the canonical source. It intentionally understands only static `export`
    declarations and static `export { ... }` clauses; dynamic or computed
    re-exports are not treated as proof.
    """
    symbols: set[str] = set(_TS_DECLARED_EXPORT_RE.findall(source))
    for clause in _TS_EXPORT_CLAUSE_RE.findall(source):
        for entry in clause.split(","):
            name = entry.strip()
            if not name or name.startswith("*"):
                continue
            # `type Foo`, `Foo as Bar` and `default as Foo` all expose the last name.
            symbols.add(name.split()[-1])
    return symbols


def _defined_or_exported_symbols(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    if path.suffix in {".ts", ".tsx"}:
        return _typescript_exported_symbols(source)

    tree = ast.parse(source, filename=str(path))
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
    module_parts = module_name.split(".")
    suffixes = [
        Path(*module_parts).with_suffix(extension).as_posix()
        for extension in (".py", ".ts", ".tsx")
    ]
    suffixes.append((Path(*module_parts) / "__init__.py").as_posix())
    return [
        ROOT / relative_path
        for relative_path in canonical_paths
        if any(Path(relative_path).as_posix().endswith(suffix) for suffix in suffixes)
    ]


def test_registry_matches_approved_capability_statuses() -> None:
    registry = _load_registry()
    capabilities = registry["capabilities"]

    assert registry["registry_version"] == "0.1.0"
    assert {
        record["capability_id"]: record["status"] for record in capabilities
    } == APPROVED_CAPABILITY_STATUSES


def test_registry_reader_is_deterministic_and_id_sorted(tmp_path: Path) -> None:
    first = RegistryReader(REGISTRY_PATH).records
    second = RegistryReader(REGISTRY_PATH).records
    assert first == second
    assert tuple(record.capability_id for record in first) == tuple(
        sorted(APPROVED_CAPABILITY_STATUSES)
    )

    document = _load_registry()
    document["capabilities"] = list(reversed(document["capabilities"]))
    reordered_path = tmp_path / "reordered.yml"
    reordered_path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    assert RegistryReader(reordered_path).records == first


def test_required_fields_identifiers_and_consumer_evidence() -> None:
    for record in _load_registry()["capabilities"]:
        assert REQUIRED_FIELDS <= record.keys()
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", record["capability_id"])
        for field in REQUIRED_FIELDS - {"known_consumers"}:
            assert record[field], f"{record['capability_id']} has empty required field {field}"
        assert record["known_consumers"] or record.get("known_consumer_exemption")


def test_canonical_consumer_and_test_paths_exist() -> None:
    for record in _load_registry()["capabilities"]:
        for field in ("canonical_paths", "known_consumers", "tests"):
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


def test_typescript_symbol_extraction_proves_real_exports_and_rejects_absent_ones() -> None:
    """The TypeScript path must verify as strictly as the Python AST path (#2526).

    Without this, a capability whose canonical source is TypeScript could declare
    any interface string and still be treated as statically proven.
    """
    source = (
        "import { helper } from './helper';\n"
        "const notExported = 1;\n"
        "export const EXPORTED_VERSION = 'v1' as const;\n"
        "export type ExportedType = Readonly<{ a: string }>;\n"
        "export function exportedFunction(value: unknown): void {}\n"
        "export class ExportedClass {}\n"
        "export { renamedSource as renamedExport };\n"
    )
    symbols = _typescript_exported_symbols(source)

    assert {
        "EXPORTED_VERSION",
        "ExportedType",
        "exportedFunction",
        "ExportedClass",
        "renamedExport",
    } <= symbols
    # Non-exported and merely imported names are not proof of a public interface.
    assert "notExported" not in symbols
    assert "helper" not in symbols


def test_typescript_backed_capabilities_resolve_against_real_canonical_sources() -> None:
    typescript_backed = [
        record
        for record in _load_registry()["capabilities"]
        for interface in record["public_interfaces"]
        if any(
            path.suffix in {".ts", ".tsx"}
            for path in _module_candidates(
                interface.split(":", 1)[0], record["canonical_paths"]
            )
        )
    ]
    assert typescript_backed, "expected at least one TypeScript-backed capability record"

    for record in typescript_backed:
        for interface in record["public_interfaces"]:
            module_name, symbol_name = interface.split(":", 1)
            candidates = _module_candidates(module_name, record["canonical_paths"])
            assert candidates, f"No canonical source file found for {interface}"
            assert any(
                symbol_name in _defined_or_exported_symbols(path) for path in candidates
            ), f"Static symbol {symbol_name} not found for {interface}"
