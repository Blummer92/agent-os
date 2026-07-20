from __future__ import annotations

import ast
from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import re

from .models import CapabilityRecord
from .reader import RegistryError, RegistryReader, repository_root

REASON_CODES = frozenset({
    "registry.invalid", "path.missing", "interface.format-invalid",
    "interface.module-missing", "interface.symbol-missing",
    "consumer.path-missing", "consumer.reference-missing", "consumer.test-only",
    "test.path-missing", "test.reference-missing", "owner.unrecognized",
    "exemption.active", "exemption.real-consumer-detected",
    "exemption.manual-review",
})
_SEVERITIES = frozenset({"warn", "manual-review", "fail"})
_RESULT_RANK = {"pass": 0, "warn": 1, "manual-review": 2, "fail": 3}
_MODULE_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
_SYMBOL_RE = re.compile(r"^[A-Za-z_]\w*$")


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    severity: str
    reason_code: str
    detail: str
    capability_id: str | None = None
    path: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in _SEVERITIES or self.reason_code not in REASON_CODES:
            raise ValueError("unsupported registry validation finding")


@dataclass(frozen=True, slots=True)
class RegistryValidationReport:
    result: str
    findings: tuple[ValidationFinding, ...]
    blockers: tuple[str, ...]
    manual_review_items: tuple[str, ...]
    exemption_findings: tuple[str, ...]
    remaining_risks: tuple[str, ...]
    authoritative: bool = False
    mutation_authorized: bool = False
    side_effects_performed: bool = False

    def __post_init__(self) -> None:
        if self.result not in _RESULT_RANK:
            raise ValueError("unsupported registry validation result")
        if self.authoritative or self.mutation_authorized or self.side_effects_performed:
            raise ValueError("registry validation must remain report-only")


def _report(findings: list[ValidationFinding]) -> RegistryValidationReport:
    ordered = tuple(sorted(set(findings), key=lambda item: (
        item.reason_code, item.capability_id or "", item.path or "", item.detail,
    )))
    result = max((item.severity for item in ordered), key=_RESULT_RANK.get, default="pass")
    return RegistryValidationReport(
        result=result,
        findings=ordered,
        blockers=tuple(item.detail for item in ordered if item.severity == "fail"),
        manual_review_items=tuple(
            item.detail for item in ordered if item.severity == "manual-review"
        ),
        exemption_findings=tuple(
            item.detail for item in ordered if item.reason_code.startswith("exemption.")
        ),
        remaining_risks=(
            "Static inspection cannot prove runtime behavior or compatibility.",
            "Ambiguous consumer intent still requires human review.",
        ),
    )


def validation_report_to_payload(report: RegistryValidationReport) -> dict[str, object]:
    return {
        "authoritative": report.authoritative,
        "blockers": list(report.blockers),
        "exemption_findings": list(report.exemption_findings),
        "findings": [
            {
                "capability_id": item.capability_id,
                "detail": item.detail,
                "path": item.path,
                "reason_code": item.reason_code,
                "severity": item.severity,
            }
            for item in report.findings
        ],
        "manual_review_items": list(report.manual_review_items),
        "mutation_authorized": report.mutation_authorized,
        "remaining_risks": list(report.remaining_risks),
        "result": report.result,
        "side_effects_performed": report.side_effects_performed,
    }


def serialize_validation_report(report: RegistryValidationReport) -> str:
    return json.dumps(
        validation_report_to_payload(report), ensure_ascii=False,
        separators=(",", ":"), sort_keys=True,
    ) + "\n"


def _safe_path(root: Path, raw: str) -> Path | None:
    value = PurePosixPath(raw)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        return None
    candidate = (root / Path(*value.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _is_test(raw: str) -> bool:
    parts = PurePosixPath(raw).parts
    return "tests" in parts or (parts and PurePosixPath(raw).name.startswith("test_"))


def _source_roots(root: Path) -> tuple[Path, ...]:
    values = [root, root / "src"]
    values.extend(sorted((root / "08_Tooling").glob("*/src")))
    return tuple(path.resolve() for path in values if path.is_dir())


def _module_files(root: Path, module: str) -> tuple[Path, ...]:
    relative = Path(*module.split("."))
    matches = []
    for source in _source_roots(root):
        for candidate in (source / relative.with_suffix(".py"), source / relative / "__init__.py"):
            if candidate.is_file():
                matches.append(candidate.resolve())
    return tuple(sorted(set(matches)))


def _evidence(path: Path) -> tuple[set[str], set[str], str]:
    text = path.read_text(encoding="utf-8")
    names: set[str] = set()
    modules: set[str] = set()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return names, modules, text
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Name)):
            names.add(node.name if hasattr(node, "name") else node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
            names.update(alias.asname or alias.name.rsplit(".", 1)[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(target.id for target in targets if isinstance(target, ast.Name))
            if any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
                value = node.value
                if isinstance(value, (ast.List, ast.Tuple)):
                    names.update(
                        item.value for item in value.elts
                        if isinstance(item, ast.Constant) and isinstance(item.value, str)
                    )
    return names, modules, text


def _references(path: Path, record: CapabilityRecord) -> bool:
    names, modules, text = _evidence(path)
    for interface in record.public_interfaces:
        if ":" not in interface:
            continue
        module, symbol = interface.rsplit(":", 1)
        if symbol in names or module in modules or interface in text:
            return True
        if any(module.endswith(f".{item}") or item.endswith(f".{module}") for item in modules):
            return True
    return False


def _agents(root: Path) -> set[str]:
    path = root / "04_Registry" / "agent-inheritance-registry.md"
    if not path.is_file():
        return set()
    result = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 3 and cells[0] not in {"Agent", "---"}:
            result.add(cells[0])
    return result


def _finding(
    findings: list[ValidationFinding], severity: str, code: str, detail: str,
    record: CapabilityRecord | None = None, path: str | None = None,
) -> None:
    findings.append(ValidationFinding(
        severity, code, detail, record.capability_id if record else None, path,
    ))


def _validate_record(root: Path, record: CapabilityRecord, agents: set[str]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for raw in record.canonical_paths:
        path = _safe_path(root, raw)
        if path is None or not path.is_file():
            _finding(findings, "fail", "path.missing", f"{record.capability_id}: missing canonical path: {raw}", record, raw)

    for interface in record.public_interfaces:
        if interface.count(":") != 1:
            _finding(findings, "fail", "interface.format-invalid", f"{record.capability_id}: invalid interface: {interface}", record, interface)
            continue
        module, symbol = interface.split(":", 1)
        if not _MODULE_RE.fullmatch(module) or not _SYMBOL_RE.fullmatch(symbol):
            _finding(findings, "fail", "interface.format-invalid", f"{record.capability_id}: invalid interface: {interface}", record, interface)
            continue
        files = _module_files(root, module)
        if not files:
            _finding(findings, "fail", "interface.module-missing", f"{record.capability_id}: missing module: {module}", record, module)
        elif len(files) > 1:
            _finding(findings, "manual-review", "interface.module-missing", f"{record.capability_id}: ambiguous module: {module}", record, module)
        else:
            try:
                names, _, _ = _evidence(files[0])
            except OSError as exc:
                _finding(findings, "manual-review", "interface.symbol-missing", f"{record.capability_id}: cannot inspect {interface}: {exc}", record, interface)
            else:
                if symbol not in names:
                    _finding(findings, "fail", "interface.symbol-missing", f"{record.capability_id}: missing symbol: {interface}", record, interface)

    if record.status == "active" and not record.known_consumers and not record.known_consumer_exemption:
        _finding(findings, "fail", "consumer.reference-missing", f"{record.capability_id}: active record lacks consumer evidence", record)
    for raw in record.known_consumers:
        path = _safe_path(root, raw)
        if path is None or not path.is_file():
            _finding(findings, "fail", "consumer.path-missing", f"{record.capability_id}: missing consumer: {raw}", record, raw)
        else:
            if _is_test(raw):
                _finding(findings, "manual-review", "consumer.test-only", f"{record.capability_id}: consumer is test-only: {raw}", record, raw)
            if not _references(path, record):
                _finding(findings, "manual-review", "consumer.reference-missing", f"{record.capability_id}: consumer lacks static reference: {raw}", record, raw)

    for raw in record.tests:
        path = _safe_path(root, raw)
        if path is None or not path.is_file():
            _finding(findings, "fail", "test.path-missing", f"{record.capability_id}: missing test: {raw}", record, raw)
        elif not _references(path, record):
            _finding(findings, "manual-review", "test.reference-missing", f"{record.capability_id}: test lacks static evidence: {raw}", record, raw)

    for role, owner in (("owner", record.owner_agent), *(("supporting agent", item) for item in record.supporting_agents)):
        if owner not in agents:
            _finding(findings, "fail", "owner.unrecognized", f"{record.capability_id}: unrecognized {role}: {owner}", record)

    if record.known_consumer_exemption:
        excluded = set(record.canonical_paths) | set(record.tests)
        matches = []
        try:
            for path in sorted(root.rglob("*.py")):
                raw = path.relative_to(root).as_posix()
                if raw in excluded or _is_test(raw) or any(part.startswith(".") for part in PurePosixPath(raw).parts):
                    continue
                if _references(path, record):
                    matches.append(raw)
        except OSError as exc:
            _finding(findings, "manual-review", "exemption.manual-review", f"{record.capability_id}: exemption scan failed: {exc}", record)
        else:
            if matches:
                _finding(findings, "warn", "exemption.real-consumer-detected", f"{record.capability_id}: exemption may be removable; consumers: {', '.join(matches)}", record)
            else:
                _finding(findings, "warn", "exemption.active", f"{record.capability_id}: active exemption requires lifecycle review", record)
    return findings


def validate_registry(
    registry_path: str | Path | None = None,
    *,
    repository_root_path: str | Path | None = None,
) -> RegistryValidationReport:
    root = Path(repository_root_path).resolve() if repository_root_path else repository_root().resolve()
    try:
        reader = RegistryReader(registry_path)
    except RegistryError as exc:
        return _report([ValidationFinding("fail", "registry.invalid", f"registry could not be loaded safely: {exc}")])
    agents = _agents(root)
    findings: list[ValidationFinding] = []
    if not agents:
        _finding(findings, "fail", "owner.unrecognized", "canonical agent registry is missing", path="04_Registry/agent-inheritance-registry.md")
    for record in reader.records:
        findings.extend(_validate_record(root, record, agents))
    return _report(findings)
