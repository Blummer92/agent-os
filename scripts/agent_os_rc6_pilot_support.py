"""Frozen RC6 technical-pilot contract, baseline guards, and case inputs."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

FROZEN_SHA = "ca980c38d74b8d3ab30ca67461a9f576281edc75"
PACKAGE_VERSION = "RC6-TF-1.1"
EXPECTED_IDS = tuple(f"T{n:02d}" for n in range(1, 25))
AUTH_EVIDENCE = "authorization=evidence-only-not-implementation-write-or-merge"
S_CLEAN_INVARIANTS = ["run(value) returns value + 1 for integer input."]
S_CLEAN_COMPATIBILITY = [
    "src.pkg.mod:run remains stable within the RC6 synthetic fixture contract."
]
S_CLEAN_CONTRACT = {
    "invariants": S_CLEAN_INVARIANTS,
    "compatibility": S_CLEAN_COMPATIBILITY,
}
T14_OVERRIDE = {"invariants": [], "compatibility": []}
REQUIRED_CASE_FIELDS = {
    "case_id", "title", "source_type", "scenario", "sanitized_input",
    "fixture_references", "expected", "threshold_classes",
}
REQUIRED_EXPECTED_FIELDS = {
    "rc3_results", "rc3_warnings", "rc3_manual_review_reasons",
    "rc4_severity", "rc4_finding_codes", "provenance_interpretation",
    "rc5_informational_statuses", "rc5_evidence_disposition",
    "base_readiness_before", "base_readiness_after",
    "implementation_authorization", "repository_write_authorization",
    "merge_authorization", "automatic_selection",
}
R_READY = """Issue Tier: 0
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
R_BLOCKED = """## Objective
Tier 0
Blocked by: unresolved dependency
"""
R_NEEDS = """## Objective
Tier 0
"""


class PilotContractError(ValueError):
    pass


def _expand_package(package: dict[str, Any]) -> dict[str, Any]:
    expanded = copy.deepcopy(package)
    defaults = expanded.pop("expected_defaults", {})
    if defaults and not isinstance(defaults, dict):
        raise PilotContractError("expected_defaults must be an object")
    for case in expanded.get("cases", []):
        if isinstance(case, dict) and isinstance(case.get("expected"), dict):
            case["expected"] = {**defaults, **case["expected"]}
    return expanded


def load_package(path: str | Path) -> dict[str, Any]:
    try:
        package = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PilotContractError(f"unable to load frozen package: {path}") from exc
    expanded = _expand_package(package)
    validate_package(expanded)
    return expanded


def validate_package(package: object) -> None:
    if not isinstance(package, dict):
        raise PilotContractError("frozen package must be a JSON object")
    package = _expand_package(package)
    for field in (
        "package_version", "frozen_sha", "frozen_identities", "thresholds",
        "synthetic_fixture_contract", "cases",
    ):
        if field not in package:
            raise PilotContractError(f"frozen package missing field: {field}")
    if package["package_version"] != PACKAGE_VERSION or package["frozen_sha"] != FROZEN_SHA:
        raise PilotContractError("frozen package identity mismatch")
    contract = package["synthetic_fixture_contract"]
    if contract != {
        "S-CLEAN": S_CLEAN_CONTRACT,
        "behavioral_contract_missing": T14_OVERRIDE,
    }:
        raise PilotContractError("synthetic fixture contract mismatch")
    cases = package["cases"]
    if not isinstance(cases, list):
        raise PilotContractError("cases must be a list")
    ids = [case.get("case_id") if isinstance(case, dict) else None for case in cases]
    if tuple(ids) != EXPECTED_IDS or len(set(ids)) != 24:
        raise PilotContractError("case IDs must be unique and exactly ordered T01-T24")
    for case in cases:
        missing = REQUIRED_CASE_FIELDS - case.keys()
        if missing:
            raise PilotContractError(f"{case['case_id']}: missing fields: {sorted(missing)}")
        expected = case["expected"]
        if not isinstance(expected, dict):
            raise PilotContractError(f"{case['case_id']}: expected must be an object")
        missing = REQUIRED_EXPECTED_FIELDS - expected.keys()
        if missing:
            raise PilotContractError(f"{case['case_id']}: missing expected fields: {sorted(missing)}")
        if any(str(key).startswith("actual_") for key in (*case.keys(), *expected.keys())):
            raise PilotContractError(f"{case['case_id']}: actual-result fields are forbidden")
    _validate_thresholds(package["thresholds"])


def _validate_thresholds(value: object) -> None:
    if not isinstance(value, dict):
        raise PilotContractError("thresholds must be an object")
    exact = {
        "false_negative": ["T01", "T21", "T22", "T23", "T24"],
        "unexpected_manual_review": ["T01", "T21", "T22", "T23", "T24"],
        "silent_automatic_selection": ["T05"],
        "contradicted_evidence_positive": ["T12"],
        "missing_active_path_positive": ["T15"],
        "active_exemptions_reviewed": ["T13"],
    }
    for name, denominator in exact.items():
        if value.get(name, {}).get("denominator") != denominator:
            raise PilotContractError(f"threshold denominator drift: {name}")
    if value.get("deterministic_repeated_output") != {"required": 24, "denominator": 24}:
        raise PilotContractError("deterministic-output threshold drift")
    zero = (
        "false_positive", "false_negative", "unexpected_manual_review",
        "false_implementation_authorization", "false_repository_write_authorization",
        "false_merge_authorization", "silent_automatic_selection",
        "contradicted_evidence_positive", "missing_active_path_positive",
    )
    if any(value.get(name, {}).get("limit") != 0 for name in zero):
        raise PilotContractError("zero-tolerance threshold drift")
    if value.get("active_exemptions_reviewed", {}).get("required_percent") != 100:
        raise PilotContractError("active-exemption threshold drift")


def load_api(root: Path) -> SimpleNamespace:
    for value in (root / "08_Tooling/reusable-capability-registry/src", root):
        text = str(value.resolve())
        if text not in sys.path:
            sys.path.insert(0, text)
    from reusable_capability_registry import RegistryReader, discover_capabilities
    from reusable_capability_registry.models import (
        Confidence, DiscoveryResult, EvidenceConfidence, RegistryProvenance,
        ValidationEvidence, ValidationFinding, ValidationReport, ValidationSeverity,
    )
    from reusable_capability_registry.provenance import compute_registry_provenance
    from reusable_capability_registry.validation import validate_registry
    from scripts.agent_os_issue_acceptance.readiness import evaluate_issue_readiness
    from scripts.agent_os_issue_acceptance.report import render_report
    from scripts.agent_os_issue_acceptance.reuse_readiness import attach_reuse_evidence
    return SimpleNamespace(**locals())


def _blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def verify_baseline(
    root: Path,
    package: dict[str, Any],
    tested_sha: str,
    api: SimpleNamespace,
    verify_head: bool,
) -> None:
    if tested_sha != FROZEN_SHA:
        raise PilotContractError(f"tested SHA must be {FROZEN_SHA}")
    if verify_head:
        try:
            head = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise PilotContractError("unable to verify baseline HEAD") from exc
        if head != FROZEN_SHA:
            raise PilotContractError(f"baseline checkout is {head}, expected {FROZEN_SHA}")
    ids = package["frozen_identities"]
    paths = {
        "registry_blob": root / "04_Registry/reusable-capabilities.yml",
        "discovery_blob": root / "08_Tooling/reusable-capability-registry/src/reusable_capability_registry/discovery.py",
        "validation_blob": root / "08_Tooling/reusable-capability-registry/src/reusable_capability_registry/validation.py",
        "rc5_blob": root / "scripts/agent_os_issue_acceptance/reuse_readiness.py",
    }
    for name, path in paths.items():
        try:
            actual = _blob_sha(path)
        except OSError as exc:
            raise PilotContractError(f"missing frozen file: {path}") from exc
        if actual != ids[name]:
            raise PilotContractError(f"frozen implementation identity mismatch: {name}")
    provenance = api.compute_registry_provenance(api.RegistryReader(paths["registry_blob"]))
    observed = (
        provenance.registry_version,
        provenance.algorithm,
        provenance.algorithm_version,
        provenance.digest,
    )
    expected = (
        ids["registry_version"],
        ids["provenance_algorithm"],
        ids["provenance_algorithm_version"],
        ids["provenance_digest"],
    )
    if observed != expected:
        raise PilotContractError("registry provenance identity drift")


def _record(**overrides: Any) -> dict[str, Any]:
    value = {
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
        "invariants": list(S_CLEAN_INVARIANTS),
        "compatibility": list(S_CLEAN_COMPATIBILITY),
    }
    value.update(overrides)
    return value


def _write_repo(
    root: Path,
    records: list[dict[str, Any]],
    missing_symbol: bool = False,
    ambiguous_alias: bool = False,
) -> None:
    for path in ("04_Registry", "02_Agent_Overlays", "src/pkg"):
        (root / path).mkdir(parents=True, exist_ok=True)
    (root / "04_Registry/reusable-capabilities.yml").write_text(
        json.dumps({"registry_version": "0.1.0", "capabilities": records}) + "\n",
        encoding="utf-8",
    )
    (root / "04_Registry/agent-inheritance-registry.md").write_text(
        "| Agent | Inherits | Overlay |\n|---|---|---|\n"
        "| Integration Manager | Global Engineering | integration-manager |\n"
        "| QA / Test Agent | Global Engineering | qa-test-agent |\n",
        encoding="utf-8",
    )
    alias = "| Legacy Name / Property | Canonical Agent | Status | Notes |\n|---|---|---|---|\n"
    if ambiguous_alias:
        alias += (
            "\n| Legacy Name / Property | Default Canonical Agent | Alternate Canonical Agent | Reason |\n"
            "|---|---|---|---|\n"
            "| PM Agent / Reporting Agent | Integration Manager | QA / Test Agent | fixture |\n"
        )
    (root / "04_Registry/legacy-agent-alias-registry.md").write_text(alias, encoding="utf-8")
    (root / "02_Agent_Overlays/integration-manager.md").write_text("# Integration Manager\n", encoding="utf-8")
    (root / "02_Agent_Overlays/qa-test-agent.md").write_text("# QA / Test Agent\n", encoding="utf-8")
    (root / "src/pkg/mod.py").write_text("def run(value):\n    return value + 1\n", encoding="utf-8")
    symbol = "missing" if missing_symbol else "run"
    (root / "src/pkg/consumer.py").write_text(
        f"from src.pkg.mod import {symbol}\n\ndef use(value):\n    return {symbol}(value)\n",
        encoding="utf-8",
    )
    (root / "test_pkg.py").write_text(
        f"from src.pkg.mod import {symbol}\n\ndef test_value():\n    assert {symbol}(1) == 2\n",
        encoding="utf-8",
    )


def synthetic(
    api: SimpleNamespace,
    variant: str,
) -> tuple[list[Any], Any, tempfile.TemporaryDirectory[str]]:
    temp = tempfile.TemporaryDirectory(prefix="rc6-pilot-")
    root = Path(temp.name)
    records, lookup, missing, ambiguous = [_record()], {"capability_id": "widget"}, False, False
    if variant == "normalized_keyword":
        records, lookup = [_record(keywords=["cached-lookup"])], {"keywords": ["CACHED_LOOKUP"]}
    elif variant == "ambiguous_candidates":
        records = [
            _record(capability_id="widget-a", name="Widget A", keywords=["shared-widget"]),
            _record(capability_id="widget-b", name="Widget B", keywords=["shared-widget"]),
        ]
        lookup = {"keywords": ["shared-widget"]}
    elif variant == "snapshot_b":
        records = [_record(summary="A changed widget summary.")]
    elif variant == "owner_case_warning":
        records = [_record(owner_agent="integration manager")]
    elif variant == "ambiguous_owner":
        records, ambiguous = [_record(owner_agent="PM Agent / Reporting Agent")], True
    elif variant == "missing_interface":
        records, missing = [_record(public_interfaces=["src.pkg.mod:missing"])], True
    elif variant == "missing_active_path":
        records = [_record(canonical_paths=["src/pkg/mod.py", "src/pkg/missing.py"])]
    elif variant == "behavioral_contract_missing":
        records = [_record(**T14_OVERRIDE)]
    _write_repo(root, records, missing, ambiguous)
    reader = api.RegistryReader(root / "04_Registry/reusable-capabilities.yml")
    results = list(api.discover_capabilities(reader, attach_provenance=True, **lookup))
    return results, api.validate_registry(root), temp


def readiness(api: SimpleNamespace, expected: str) -> Any:
    body = {"ready": R_READY, "blocked": R_BLOCKED, "needs-decision": R_NEEDS}[expected]
    value = api.evaluate_issue_readiness(body)
    if value.outcome.value != expected:
        raise PilotContractError(
            f"readiness fixture produced {value.outcome.value}, expected {expected}"
        )
    return value


def evidence(
    case: dict[str, Any],
    root: Path,
    api: SimpleNamespace,
) -> tuple[Any, list[Any], Any, Any, list[Any]]:
    scenario, expected = case["scenario"], case["expected"]
    base, keep = readiness(api, expected["base_readiness_before"]), []
    if scenario in {"current_exemption", "current_clean"}:
        reader = api.RegistryReader(root / "04_Registry/reusable-capabilities.yml")
        cid = "issue-readiness-evaluator" if scenario == "current_exemption" else "issue-label-checker"
        results = list(api.discover_capabilities(reader, capability_id=cid, attach_provenance=True))
        report = api.validate_registry(root)
    elif scenario == "no_match":
        _, report, temp = synthetic(api, "clean_verified")
        keep.append(temp)
        reader = api.RegistryReader(Path(temp.name) / "04_Registry/reusable-capabilities.yml")
        results = list(
            api.discover_capabilities(reader, capability_id="does-not-exist", attach_provenance=True)
        )
    elif scenario == "provenance_mismatch":
        results, _, a = synthetic(api, "clean_verified")
        _, report, b = synthetic(api, "snapshot_b")
        keep += [a, b]
    elif scenario == "missing_provenance":
        results, report, temp = synthetic(api, "clean_verified")
        keep.append(temp)
        results = [replace(item, provenance=None) for item in results]
    elif scenario == "unsupported_provenance":
        results, _, temp = synthetic(api, "clean_verified")
        keep.append(temp)
        p = api.RegistryProvenance("future-registry-provenance", 999, "0.1.0", "0" * 64)
        results = [replace(item, provenance=p) for item in results]
        report = api.ValidationReport.from_findings(
            [], provenance=p, capabilities_checked=1, checks_run=1
        )
    elif scenario == "unverified_boundary":
        results, report, temp = synthetic(api, "clean_verified")
        keep.append(temp)
        results = [replace(item, confidence=api.Confidence.UNVERIFIED) for item in results]
    elif scenario in {"contradicted_evidence", "future_validation_code"}:
        results, _, temp = synthetic(api, "clean_verified")
        keep.append(temp)
        future = scenario == "future_validation_code"
        finding = api.ValidationFinding(
            "future.surface-check" if future else "contract.contradicted",
            api.EvidenceConfidence.MANUAL_REVIEW if future else api.EvidenceConfidence.CONTRADICTED,
            api.ValidationSeverity.MANUAL_REVIEW if future else api.ValidationSeverity.WARN,
            "widget",
            "future" if future else "contract",
            "Future validation evidence requires review." if future else "Caller evidence is contradicted.",
            (api.ValidationEvidence("src/pkg/mod.py", 1, "run", "fixture", "structured evidence"),),
            "future code is not yet governed" if future else None,
        )
        report = api.ValidationReport.from_findings(
            [finding],
            provenance=results[0].provenance,
            capabilities_checked=1,
            checks_run=1,
        )
    elif scenario == "malformed_discovery":
        _, report, temp = synthetic(api, "clean_verified")
        keep.append(temp)
        results = ["not-a-result"]
    elif scenario == "malformed_validation":
        results, _, temp = synthetic(api, "clean_verified")
        keep.append(temp)
        report = object()
    else:
        variant = scenario if scenario not in {
            "blocked_readiness", "needs_decision_readiness", "clean_verified"
        } else "clean_verified"
        results, report, temp = synthetic(api, variant)
        keep.append(temp)
    attached = api.attach_reuse_evidence(base, results, report)
    return base, results, report, attached, keep
