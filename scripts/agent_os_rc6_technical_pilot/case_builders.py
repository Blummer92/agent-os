"""Build sanitized ordinary, current-real, and boundary inputs for T01-T24."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from reusable_capability_registry.discovery import discover_capabilities
from reusable_capability_registry.models import (
    CapabilityRecord,
    Confidence,
    DiscoveryResult,
    EvidenceConfidence,
    RegistryProvenance,
    ValidationEvidence,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
)
from reusable_capability_registry.reader import RegistryReader
from reusable_capability_registry.validation import validate_registry
from scripts.agent_os_issue_acceptance.readiness import (
    ReadinessResult,
    evaluate_issue_readiness,
)

_READY_BODY = """Issue Tier: 0
## Objective
Remove one deprecation warning.
## Owner
QA / Test Agent
## Allowed Files
- src/example.py
## Validation
- pytest tests/test_example.py
## Completion Criterion
- Warning no longer appears.
## Documentation impact
docs-not-required
## Documentation exemption reason
No documented behavior changes.
"""
_BLOCKED_BODY = """## Objective
Tier 0
Blocked by: unresolved dependency
"""
_NEEDS_BODY = """## Objective
Tier 0
"""


@dataclass(frozen=True)
class ExecutionInputs:
    base: ReadinessResult
    discovery_for_adapter: object
    discovery_for_result: tuple[DiscoveryResult, ...]
    validation_for_adapter: object
    validation_for_result: ValidationReport | None
    boundary: str = "ordinary"
    provenance_override: tuple[str, ...] | None = None


class ExecutionStrategyError(ValueError):
    """Raised when a frozen case references an unsupported strategy."""


def build_execution_inputs(
    case: Mapping[str, Any], repository_root: Path, temp_root: Path
) -> ExecutionInputs:
    strategy = case["strategy"]
    base = _base_readiness(case["readiness_input"])
    if strategy == "synthetic-clean":
        return _ordinary_inputs(base, _build_synthetic(temp_root, [_default_cap()]), "widget")
    if strategy == "synthetic-keyword":
        root = _build_synthetic(temp_root, [_default_cap(keywords=["cached-lookup"])])
        return _ordinary_inputs(base, root, keywords=["CACHED_LOOKUP"])
    if strategy == "synthetic-no-match":
        root = _build_synthetic(temp_root, [_default_cap()])
        return _ordinary_inputs(base, root, "does-not-exist")
    if strategy == "synthetic-ambiguous":
        root = _build_synthetic(
            temp_root,
            [
                _default_cap(
                    capability_id="widget-a",
                    name="Widget A",
                    keywords=["shared-widget"],
                ),
                _default_cap(
                    capability_id="widget-b",
                    name="Widget B",
                    keywords=["shared-widget"],
                ),
            ],
        )
        return _ordinary_inputs(base, root, keywords=["shared-widget"])
    if strategy == "synthetic-provenance-mismatch":
        root_a = _build_synthetic(temp_root / "a", [_default_cap(summary="Snapshot A")])
        root_b = _build_synthetic(temp_root / "b", [_default_cap(summary="Snapshot B")])
        reader = RegistryReader(root_a / "04_Registry/reusable-capabilities.yml")
        discovery = discover_capabilities(
            reader,
            capability_id="widget",
            attach_provenance=True,
        )
        report = validate_registry(root_b)
        return ExecutionInputs(base, discovery, discovery, report, report)
    if strategy == "synthetic-missing-provenance":
        root = _build_synthetic(temp_root, [_default_cap()])
        reader = RegistryReader(root / "04_Registry/reusable-capabilities.yml")
        discovery = discover_capabilities(
            reader,
            capability_id="widget",
            attach_provenance=False,
        )
        report = validate_registry(root)
        return ExecutionInputs(base, discovery, discovery, report, report)
    if strategy == "validation-owner-case":
        root = _build_synthetic(temp_root, [_default_cap(owner_agent="QA Agent")])
        return _ordinary_inputs(base, root, "widget")
    if strategy == "validation-owner-ambiguous":
        root = _build_synthetic(temp_root, [_default_cap(owner_agent="Source Reviewer")])
        return _ordinary_inputs(base, root, "widget")
    if strategy == "validation-interface-missing":
        root = _build_synthetic(
            temp_root,
            [_default_cap(public_interfaces=["src.pkg.mod:missing"])],
            files={
                "src/pkg/consumer.py": (
                    "from src.pkg.mod import missing\n\n\ndef use(n):\n    return missing(n)\n"
                ),
                "test_pkg.py": (
                    "from src.pkg.mod import missing\n\n\ndef test_missing():\n"
                    "    assert missing(1) == 2\n"
                ),
            },
        )
        return _ordinary_inputs(base, root, "widget")
    if strategy == "synthetic-no-contract":
        root = _build_synthetic(
            temp_root,
            [_default_cap(invariants=[], compatibility=[])],
        )
        return _ordinary_inputs(base, root, "widget")
    if strategy == "validation-path-missing":
        root = _build_synthetic(
            temp_root,
            [_default_cap(canonical_paths=["src/pkg/missing.py", "src/pkg/mod.py"])],
        )
        return _ordinary_inputs(base, root, "widget")
    if strategy == "current-issue-readiness":
        return _current_inputs(base, repository_root, "issue-readiness-evaluator")
    if strategy == "current-issue-label":
        return _current_inputs(base, repository_root, "issue-label-checker")
    if strategy == "boundary-unverified":
        root = _build_synthetic(temp_root, [_default_cap()])
        reader = RegistryReader(root / "04_Registry/reusable-capabilities.yml")
        ordinary = discover_capabilities(
            reader,
            capability_id="widget",
            attach_provenance=True,
        )[0]
        discovery = (
            DiscoveryResult(
                ordinary.capability,
                Confidence.UNVERIFIED,
                ("caller-supplied-boundary",),
                ordinary.warnings,
                (),
                ordinary.provenance,
            ),
        )
        report = validate_registry(root)
        return ExecutionInputs(
            base,
            discovery,
            discovery,
            report,
            report,
            boundary="public-model",
        )
    if strategy == "boundary-unsupported-provenance":
        provenance = RegistryProvenance(
            "registry-canonical-records",
            2,
            "0.1.0",
            "a" * 64,
        )
        discovery = (_boundary_discovery(provenance=provenance),)
        report = ValidationReport.from_findings(
            [],
            provenance=provenance,
            capabilities_checked=1,
            checks_run=1,
        )
        return ExecutionInputs(
            base,
            discovery,
            discovery,
            report,
            report,
            boundary="public-model",
        )
    if strategy == "boundary-contradicted":
        provenance = RegistryProvenance(
            "registry-canonical-records",
            1,
            "0.1.0",
            "a" * 64,
        )
        discovery = (
            _boundary_discovery(
                provenance=provenance,
                evidence=("exact-capability-id-match",),
            ),
        )
        finding = ValidationFinding(
            "path.missing",
            EvidenceConfidence.CONTRADICTED,
            ValidationSeverity.WARN,
            "widget",
            "path",
            "caller-supplied contradicted boundary evidence",
            (
                ValidationEvidence(
                    "src/pkg/missing.py",
                    1,
                    None,
                    "boundary",
                    "contradicted",
                ),
            ),
        )
        report = ValidationReport.from_findings(
            [finding],
            provenance=provenance,
            capabilities_checked=1,
            checks_run=1,
        )
        return ExecutionInputs(
            base,
            discovery,
            discovery,
            report,
            report,
            boundary="public-model",
        )
    if strategy == "boundary-malformed-discovery":
        report = _clean_boundary_report()
        return ExecutionInputs(
            base,
            ["not-a-discovery-result"],
            (),
            report,
            report,
            boundary="malformed-input",
            provenance_override=("not-interpreted",),
        )
    if strategy == "boundary-malformed-validation":
        provenance = RegistryProvenance(
            "registry-canonical-records",
            1,
            "0.1.0",
            "a" * 64,
        )
        discovery = (
            _boundary_discovery(
                provenance=provenance,
                evidence=("exact-capability-id-match",),
            ),
        )
        return ExecutionInputs(
            base,
            discovery,
            discovery,
            "not-a-validation-report",
            None,
            boundary="malformed-input",
            provenance_override=("not-interpreted",),
        )
    if strategy == "boundary-future-code":
        provenance = RegistryProvenance(
            "registry-canonical-records",
            1,
            "0.1.0",
            "a" * 64,
        )
        discovery = (
            _boundary_discovery(
                provenance=provenance,
                evidence=("exact-capability-id-match",),
            ),
        )
        finding = ValidationFinding(
            "future.surface-check",
            EvidenceConfidence.MANUAL_REVIEW,
            ValidationSeverity.MANUAL_REVIEW,
            "widget",
            "future",
            "future validation surface requires manual review",
            (
                ValidationEvidence(
                    "src/pkg/mod.py",
                    2,
                    "src.pkg.mod:run",
                    "future",
                    "first",
                ),
                ValidationEvidence(None, None, None, "future", "second"),
            ),
            "future validation code is not yet governed",
        )
        report = ValidationReport.from_findings(
            [finding],
            provenance=provenance,
            capabilities_checked=1,
            checks_run=1,
        )
        return ExecutionInputs(
            base,
            discovery,
            discovery,
            report,
            report,
            boundary="public-model",
        )
    raise ExecutionStrategyError(f"unsupported frozen strategy: {strategy}")


def _ordinary_inputs(
    base: ReadinessResult,
    root: Path,
    capability_id: str | None = None,
    *,
    keywords: Iterable[str] = (),
) -> ExecutionInputs:
    reader = RegistryReader(root / "04_Registry/reusable-capabilities.yml")
    discovery = discover_capabilities(
        reader,
        capability_id=capability_id,
        keywords=keywords,
        attach_provenance=True,
    )
    report = validate_registry(root)
    return ExecutionInputs(base, discovery, discovery, report, report)


def _current_inputs(
    base: ReadinessResult,
    repository_root: Path,
    capability_id: str,
) -> ExecutionInputs:
    reader = RegistryReader(repository_root / "04_Registry/reusable-capabilities.yml")
    discovery = discover_capabilities(
        reader,
        capability_id=capability_id,
        attach_provenance=True,
    )
    full_report = validate_registry(repository_root)
    findings = [
        finding
        for finding in full_report.findings
        if finding.capability_id == capability_id
    ]
    report = ValidationReport.from_findings(
        findings,
        provenance=full_report.provenance,
        capabilities_checked=1,
        checks_run=full_report.checks_run,
    )
    return ExecutionInputs(base, discovery, discovery, report, report)


def _base_readiness(name: str) -> ReadinessResult:
    bodies = {
        "R-READY": _READY_BODY,
        "R-BLOCKED": _BLOCKED_BODY,
        "R-NEEDS": _NEEDS_BODY,
    }
    try:
        body = bodies[name]
    except KeyError as exc:
        raise ExecutionStrategyError(f"unsupported readiness input: {name}") from exc
    return evaluate_issue_readiness(body)


def _default_cap(**overrides: Any) -> dict[str, Any]:
    cap: dict[str, Any] = {
        "capability_id": "widget",
        "name": "Widget",
        "summary": "A widget.",
        "status": "active",
        "canonical_paths": ["src/pkg/mod.py"],
        "public_interfaces": ["src.pkg.mod:run"],
        "owner_agent": "Integration Manager",
        "known_consumers": ["src/pkg/consumer.py"],
        "tests": ["test_pkg.py"],
        "keywords": ["widget"],
        "reuse_guidance": "Reuse the widget.",
        "side_effects": ["Performs no writes."],
    }
    cap.update(overrides)
    return cap


def _build_synthetic(
    root: Path,
    capabilities: list[dict[str, Any]],
    *,
    files: Mapping[str, str] | None = None,
) -> Path:
    default_files = {
        "04_Registry/reusable-capabilities.yml": yaml.safe_dump(
            {"registry_version": "0.1.0", "capabilities": capabilities},
            sort_keys=False,
            allow_unicode=True,
        ),
        "04_Registry/agent-inheritance-registry.md": (
            "# Agent Inheritance Registry\n\n"
            "| Agent | Inherits | Overlay |\n|---|---|---|\n"
            "| Integration Manager | X | integration-manager |\n"
            "| QA / Test Agent | X | qa-test-agent |\n"
        ),
        "04_Registry/legacy-agent-alias-registry.md": (
            "# Legacy Agent Alias Registry\n\n## Alias Table\n\n"
            "| Legacy Name / Property | Canonical Agent | Current Overlay | Status | Notes |\n"
            "|---|---|---|---|---|\n"
            "| QA Agent | QA / Test Agent | `qa-test-agent` | active alias | n |\n"
            "| Source Reviewer | Integration Manager | `integration-manager` | provisional | n |\n\n"
            "## Ambiguous Legacy Values\n\n"
            "| Legacy Name / Property | Default Canonical Agent | Alternate Canonical Agent | Disambiguation Rule |\n"
            "|---|---|---|---|\n"
            "| Dashboard Agent | Integration Manager | QA / Test Agent | context |\n"
        ),
        "04_Registry/responsibility-matrix.md": (
            "# Responsibility Matrix\n\n| Responsibility | Primary | Support |\n"
            "|---|---|---|\n| x | QA / Test Agent | Integration Manager |\n"
        ),
        "02_Agent_Overlays/integration-manager.md": "overlay\n",
        "02_Agent_Overlays/qa-test-agent.md": "overlay\n",
        "src/pkg/mod.py": "def run(value):\n    return value + 1\n",
        "src/pkg/consumer.py": (
            "from src.pkg.mod import run\n\n\ndef use(n):\n    return run(n)\n"
        ),
        "test_pkg.py": (
            "from src.pkg.mod import run\n\n\ndef test_run():\n    assert run(1) == 2\n"
        ),
    }
    default_files.update(files or {})
    for relative, content in default_files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return root


def _boundary_record() -> CapabilityRecord:
    return CapabilityRecord(
        capability_id="widget",
        name="Widget",
        summary="A widget.",
        status="active",
        canonical_paths=("src/pkg/mod.py",),
        public_interfaces=("src.pkg.mod:run",),
        owner_agent="Integration Manager",
        supporting_agents=(),
        known_consumers=("src/pkg/consumer.py",),
        known_consumer_exemption=None,
        tests=("test_pkg.py",),
        keywords=("widget",),
        reuse_guidance="Reuse the widget.",
        side_effects=("Performs no writes.",),
    )


def _boundary_discovery(
    *,
    provenance: RegistryProvenance,
    evidence: tuple[str, ...] = ("caller-supplied-boundary",),
) -> DiscoveryResult:
    return DiscoveryResult(
        _boundary_record(),
        Confidence.VERIFIED,
        evidence,
        (),
        (),
        provenance,
    )


def _clean_boundary_report() -> ValidationReport:
    provenance = RegistryProvenance(
        "registry-canonical-records",
        1,
        "0.1.0",
        "a" * 64,
    )
    return ValidationReport.from_findings(
        [],
        provenance=provenance,
        capabilities_checked=1,
        checks_run=1,
    )


def provenance_state(
    discovery: RegistryProvenance | None,
    validation: RegistryProvenance | None,
) -> str:
    if discovery is None or validation is None:
        return "missing"
    if discovery != validation:
        return "mismatch"
    return "matched" if discovery.is_supported else "unsupported"


def relevant_findings(
    report: ValidationReport | None,
    capability_ids: list[str],
) -> tuple[ValidationFinding, ...]:
    if report is None:
        return ()
    if not capability_ids:
        return report.findings
    ids = set(capability_ids)
    return tuple(
        finding for finding in report.findings if finding.capability_id in ids
    )
