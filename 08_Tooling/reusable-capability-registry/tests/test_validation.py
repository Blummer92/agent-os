"""Orchestration tests for RC4 report-only validation (#494 / #254)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from reusable_capability_registry import RegistryReader, discover_capabilities
from reusable_capability_registry.models import (
    EvidenceConfidence,
    RegistryProvenance,
    ValidationReport,
    ValidationSeverity,
)
from reusable_capability_registry.provenance import compute_registry_provenance
from reusable_capability_registry.serialization import serialize_validation_report
from reusable_capability_registry.validation import validate_registry

FIXTURES = Path(__file__).parent / "fixtures"
CLEAN = FIXTURES / "validation" / "repositories" / "clean"

_INHERIT = (
    "# Agent Inheritance Registry\n\n"
    "| Agent | Inherits | Overlay |\n|---|---|---|\n"
    "| Integration Manager | X | integration-manager |\n"
    "| QA / Test Agent | X | qa-test-agent |\n"
)
_ALIAS = (
    "# Legacy Agent Alias Registry\n\n## Alias Table\n\n"
    "| Legacy Name / Property | Canonical Agent | Current Overlay | Status | Notes |\n|---|---|---|---|---|\n"
    "| QA Agent | QA / Test Agent | `qa-test-agent` | active alias | n |\n"
    "| Source Reviewer | Integration Manager | `integration-manager` | provisional | n |\n"
    "| Ghost Alias | No Such Agent | `no-such` | active alias | n |\n\n"
    "## Ambiguous Legacy Values\n\n"
    "| Legacy Name / Property | Default Canonical Agent | Alternate Canonical Agent | Disambiguation Rule |\n|---|---|---|---|\n"
    "| Dashboard Agent | Integration Manager | QA / Test Agent | context |\n"
)
_RESPONSIBILITY = "# Responsibility Matrix\n\n| Responsibility | Primary | Support |\n|---|---|---|\n| x | QA / Test Agent | Integration Manager |\n"

_CLEAN_MOD = "def run(value):\n    return value + 1\n"
_CLEAN_CONSUMER = "from src.pkg.mod import run\n\n\ndef use(n):\n    return run(n)\n"
_CLEAN_TEST = "from src.pkg.mod import run\n\n\ndef test_run():\n    assert run(1) == 2\n"


def _default_cap(**overrides) -> dict:
    cap = {
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


def _build(tmp_path: Path, capabilities: list[dict], files: dict[str, str] | None = None) -> Path:
    root = tmp_path
    default_files = {
        "04_Registry/reusable-capabilities.yml": yaml.safe_dump(
            {"registry_version": "0.1.0", "capabilities": capabilities}, sort_keys=False, allow_unicode=True
        ),
        "04_Registry/agent-inheritance-registry.md": _INHERIT,
        "04_Registry/legacy-agent-alias-registry.md": _ALIAS,
        "04_Registry/responsibility-matrix.md": _RESPONSIBILITY,
        "02_Agent_Overlays/integration-manager.md": "overlay\n",
        "02_Agent_Overlays/qa-test-agent.md": "overlay\n",
        "src/pkg/mod.py": _CLEAN_MOD,
        "src/pkg/consumer.py": _CLEAN_CONSUMER,
        "test_pkg.py": _CLEAN_TEST,
    }
    default_files.update(files or {})
    for rel, content in default_files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def _codes(report: ValidationReport) -> set[str]:
    return {finding.code for finding in report.findings}


def _by_code(report: ValidationReport, code: str):
    return [finding for finding in report.findings if finding.code == code]


# --- clean, provenance, determinism ----------------------------------------


def test_clean_fixture_is_pass_with_provenance():
    report = validate_registry(CLEAN)
    assert report.severity is ValidationSeverity.PASS
    assert report.findings == ()
    assert report.report_version == "1.0"
    assert report.provenance is not None
    assert report.provenance.algorithm == "registry-canonical-records"


def test_built_clean_capability_is_pass(tmp_path):
    root = _build(tmp_path, [_default_cap()])
    report = validate_registry(root)
    assert report.severity is ValidationSeverity.PASS, _codes(report)


def test_repeated_serialization_is_byte_identical(tmp_path):
    root = _build(tmp_path, [_default_cap()])
    assert serialize_validation_report(validate_registry(root)) == serialize_validation_report(validate_registry(root))


def test_provenance_matches_reader_snapshot_and_discovery(tmp_path):
    root = _build(tmp_path, [_default_cap()])
    reg = root / "04_Registry" / "reusable-capabilities.yml"
    report = validate_registry(root)
    reader = RegistryReader(reg)
    assert report.provenance == compute_registry_provenance(reader)
    discovered = discover_capabilities(reader, capability_id="widget", attach_provenance=True)
    assert discovered[0].provenance == report.provenance  # RC3<->RC4 same snapshot


# --- structural / provenance failure ---------------------------------------


def test_malformed_registry_fails_with_null_provenance(tmp_path):
    root = _build(tmp_path, [_default_cap()], files={"04_Registry/reusable-capabilities.yml": "capabilities: [oops\n"})
    report = validate_registry(root)
    assert report.severity is ValidationSeverity.FAIL
    assert report.provenance is None
    assert "structure.malformed-registry" in _codes(report)


def test_unsupported_version_fails_closed(tmp_path):
    doc = yaml.safe_dump({"registry_version": "9.9.9", "capabilities": []}, sort_keys=False)
    root = _build(tmp_path, [_default_cap()], files={"04_Registry/reusable-capabilities.yml": doc})
    report = validate_registry(root)
    assert "structure.unsupported-registry-version" in _codes(report)
    assert report.provenance is None


def test_expected_provenance_match_mismatch_and_unsupported(tmp_path):
    root = _build(tmp_path, [_default_cap()])
    good = compute_registry_provenance(RegistryReader(root / "04_Registry" / "reusable-capabilities.yml"))
    assert "structure.provenance-mismatch" not in _codes(validate_registry(root, expected_provenance=good))
    wrong = RegistryProvenance(good.algorithm, good.algorithm_version, good.registry_version, "b" * 64)
    assert "structure.provenance-mismatch" in _codes(validate_registry(root, expected_provenance=wrong))
    unsupported = RegistryProvenance("other-algorithm", 2, "0.1.0", "c" * 64)
    assert "structure.provenance-unsupported" in _codes(validate_registry(root, expected_provenance=unsupported))


# --- consumer classifications ----------------------------------------------


@pytest.mark.parametrize(
    "consumer_src,consumer_path,expected",
    [
        ("from src.pkg.mod import run\n\n\ndef f():\n    return run(1)\n", "src/pkg/c.py", None),
        ("import typing\nif typing.TYPE_CHECKING:\n    from src.pkg.mod import run\n", "src/pkg/c.py", "consumer.typing-only"),
        ("import src.pkg.mod\n", "src/pkg/c.py", "consumer.package-import-only"),
        ("# uses run somewhere\nX = 'run'\n", "src/pkg/c.py", "consumer.weak-text-only"),
        ("x = 1\n", "src/pkg/c.py", "consumer.interface-missing"),
        ("import importlib\nm = importlib.import_module('src.pkg.mod')\n", "src/pkg/c.py", "consumer.dynamic-usage"),
        ("if x:\n    from src.pkg.mod import run\n", "src/pkg/c.py", "consumer.conditional-usage"),
        ("def run(:\n", "src/pkg/c.py", "consumer.syntax-error"),
    ],
)
def test_consumer_classifications(tmp_path, consumer_src, consumer_path, expected):
    cap = _default_cap(known_consumers=[consumer_path])
    root = _build(tmp_path, [cap], files={consumer_path: consumer_src})
    codes = _codes(validate_registry(root))
    if expected is None:
        assert not any(c.startswith("consumer.") for c in codes), codes
    else:
        assert expected in codes, codes


def test_test_listed_as_consumer_is_not_operational(tmp_path):
    cap = _default_cap(known_consumers=["tests/test_helper.py"])
    root = _build(tmp_path, [cap], files={"tests/test_helper.py": _CLEAN_TEST})
    assert "consumer.path-not-operational" in _codes(validate_registry(root))


# --- test-evidence classifications -----------------------------------------


@pytest.mark.parametrize(
    "test_src,test_path,expected",
    [
        ("from src.pkg.mod import run\n\n\ndef test_a():\n    assert run(1) == 2\n", "test_pkg.py", None),
        ("from src.pkg.mod import run\n\n\ndef test_a():\n    run\n", "test_pkg.py", "test.import-only"),
        ("x = 1\n", "test_pkg.py", "test.unrelated"),
        ("# run in a comment\ny = 'run'\n", "test_pkg.py", "test.weak-text-only"),
        ("import importlib\nm = importlib.import_module('x')\n", "test_pkg.py", "test.dynamic-usage"),
        ("import pytest\n\n\n@pytest.mark.skip\ndef test_a():\n    from src.pkg.mod import run\n    run(1)\n", "test_pkg.py", "test.skipped-only"),
        ("def test_a(:\n", "test_pkg.py", "test.syntax-error"),
        ("from .helper import go\n\n\ndef test_a():\n    assert go()\n", "test_pkg.py", "test.helper-boundary-unresolved"),
    ],
)
def test_test_classifications(tmp_path, test_src, test_path, expected):
    cap = _default_cap(tests=[test_path])
    root = _build(tmp_path, [cap], files={test_path: test_src})
    codes = _codes(validate_registry(root))
    if expected is None:
        assert not any(c.startswith("test.") for c in codes), codes
    else:
        assert expected in codes, codes


def test_test_path_not_a_test(tmp_path):
    cap = _default_cap(tests=["src/pkg/impl.py"])
    root = _build(tmp_path, [cap], files={"src/pkg/impl.py": _CLEAN_MOD})
    assert "test.path-not-test" in _codes(validate_registry(root))


# --- lifecycle matrix ------------------------------------------------------


def test_missing_interface_is_lifecycle_sensitive(tmp_path):
    # active -> fail; replaced -> warn (with a resolvable successor)
    active = _build(tmp_path / "a", [_default_cap(public_interfaces=["src.pkg.mod:missing"])])
    report = validate_registry(active)
    assert any(f.code == "interface.symbol-missing" and f.severity is ValidationSeverity.FAIL for f in report.findings)

    caps = [
        _default_cap(capability_id="successor"),
        _default_cap(capability_id="widget", status="replaced", deprecated_by="successor",
                     public_interfaces=["src.pkg.mod:missing"]),
    ]
    replaced_root = _build(tmp_path / "b", caps)
    report2 = validate_registry(replaced_root)
    symbol_findings = [f for f in report2.findings if f.code == "interface.symbol-missing" and f.capability_id == "widget"]
    assert symbol_findings and symbol_findings[0].severity is ValidationSeverity.WARN


def test_internal_only_needs_no_operational_consumer(tmp_path):
    cap = _default_cap(status="internal-only", known_consumers=[])
    root = _build(tmp_path, [cap])
    assert "exemption.missing-required" not in _codes(validate_registry(root))


def test_active_missing_consumer_without_exemption_fails(tmp_path):
    cap = _default_cap(known_consumers=[])
    report = validate_registry(_build(tmp_path, [cap]))
    findings = _by_code(report, "exemption.missing-required")
    assert findings and findings[0].severity is ValidationSeverity.FAIL


def test_successor_missing_and_resolves(tmp_path):
    missing = _build(tmp_path / "a", [_default_cap(status="replaced", deprecated_by="ghost")])
    assert "structure.successor-missing" in _codes(validate_registry(missing))
    caps = [_default_cap(capability_id="successor"),
            _default_cap(capability_id="widget", status="deprecated", deprecated_by="successor")]
    ok = _build(tmp_path / "b", caps)
    assert "structure.successor-missing" not in _codes(validate_registry(ok))


# --- ownership & exemption -------------------------------------------------


@pytest.mark.parametrize(
    "owner,expected",
    [
        ("Integration Manager", None),
        ("Nonexistent Agent", "owner.unknown-agent"),
        ("QA Agent", "owner.canonical-case"),          # active alias -> canonicalization warn
        ("Source Reviewer", "owner.ambiguous-alias"),  # provisional
        ("Dashboard Agent", "owner.ambiguous-alias"),  # ambiguous table
        ("Ghost Alias", "owner.unmapped-alias"),       # alias target not canonical
    ],
)
def test_owner_resolution(tmp_path, owner, expected):
    root = _build(tmp_path, [_default_cap(owner_agent=owner)])
    codes = _codes(validate_registry(root))
    if expected is None:
        assert not any(c.startswith("owner.") for c in codes), codes
    else:
        assert expected in codes, codes


def test_owner_overlay_missing(tmp_path):
    root = _build(tmp_path, [_default_cap()], files={"02_Agent_Overlays/integration-manager.md": None} if False else {})
    (root / "02_Agent_Overlays" / "integration-manager.md").unlink()
    assert "owner.overlay-missing" in _codes(validate_registry(root))


def test_owner_source_conflict(tmp_path):
    conflicted = _INHERIT + "| Integration Manager | X | other-overlay |\n"
    root = _build(tmp_path, [_default_cap()], files={"04_Registry/agent-inheritance-registry.md": conflicted})
    assert "owner.source-conflict" in _codes(validate_registry(root))


def test_support_duplicate_and_primary_also_support(tmp_path):
    # distinct strings that resolve to the same canonical agents (the reader rejects
    # exact duplicates, so duplication is detected after alias canonicalization).
    cap = _default_cap(owner_agent="Integration Manager",
                       supporting_agents=["Integration Manager", "QA / Test Agent", "QA Agent"])
    codes = _codes(validate_registry(_build(tmp_path, [cap])))
    assert "owner.primary-also-support" in codes
    assert "owner.duplicate-support" in codes


@pytest.mark.parametrize(
    "overrides,expected",
    [
        (dict(known_consumers=[], known_consumer_exemption="Approved: no consumer yet."), "exemption.active-no-consumer"),
        (dict(known_consumers=["tests/test_h.py"], known_consumer_exemption="Approved."), "exemption.active-test-only"),
        (dict(known_consumers=["src/pkg/consumer.py"], known_consumer_exemption="Approved."), "exemption.recommend-review"),
    ],
)
def test_exemption_outcomes(tmp_path, overrides, expected):
    files = {"tests/test_h.py": _CLEAN_TEST} if "tests/test_h.py" in overrides.get("known_consumers", []) else {}
    root = _build(tmp_path, [_default_cap(**overrides)], files=files)
    assert expected in _codes(validate_registry(root))


def test_exemption_reason_is_bounded(tmp_path):
    long_reason = "x" * 400
    cap = _default_cap(known_consumers=[], known_consumer_exemption=long_reason)
    report = validate_registry(_build(tmp_path, [cap]))
    finding = _by_code(report, "exemption.active-no-consumer")[0]
    detail = finding.evidence[0].detail
    assert len(long_reason) > 240 and "+160 chars" in detail and long_reason not in detail


# --- scale, mutation-safety, live registry ---------------------------------


def test_more_than_seven_records(tmp_path):
    caps = [_default_cap(capability_id=f"widget-{i:02d}") for i in range(8)]
    report = validate_registry(_build(tmp_path, caps))
    assert report.capabilities_checked == 8


def test_validation_mutates_nothing(tmp_path):
    root = _build(tmp_path, [_default_cap()])
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    validate_registry(root)
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    assert before == after  # same files, same content, nothing created


def test_live_registry_is_deterministic_with_provenance():
    repo_root = Path(__file__).resolve().parents[3]
    report = validate_registry(repo_root)
    assert report.provenance is not None
    assert report.capabilities_checked == 13
    assert serialize_validation_report(report) == serialize_validation_report(validate_registry(repo_root))
    # RC4 provenance equals the discovery snapshot provenance.
    reader = RegistryReader()
    assert report.provenance == compute_registry_provenance(reader)


def test_rc4_does_not_import_readiness_modules():
    import reusable_capability_registry.validation as validation_module

    source = Path(validation_module.__file__).read_text(encoding="utf-8")
    assert "readiness" not in source
    assert "issue_acceptance" not in source
