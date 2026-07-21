from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from reusable_capability_registry import CapabilityRecord, Confidence, DiscoveryResult, RegistryReader, discover_capabilities

FIXTURES = Path(__file__).parent / "fixtures"


def make_record() -> CapabilityRecord:
    return CapabilityRecord(
        capability_id="alpha",
        name="Alpha",
        summary="Alpha summary",
        status="active",
        canonical_paths=("alpha.py",),
        public_interfaces=("alpha:run",),
        owner_agent="Integration Manager",
        supporting_agents=(),
        known_consumers=(),
        known_consumer_exemption=None,
        tests=(),
        keywords=("alpha",),
        reuse_guidance="Reuse alpha.",
        side_effects=(),
    )


def test_models_are_frozen_slotted_and_nested_sequences_are_immutable():
    record = make_record()
    result = DiscoveryResult(record, Confidence.VERIFIED, ("exact-capability-id-match",), (), ())
    assert not hasattr(record, "__dict__")
    assert isinstance(record.keywords, tuple)
    with pytest.raises(FrozenInstanceError):
        setattr(record, "status", "deprecated")
    with pytest.raises(AttributeError):
        result.evidence_basis.append("x")


def test_canonical_and_derived_fields_are_separated():
    record = RegistryReader(FIXTURES / "valid_registry.yml").by_id("alpha-reader")
    assert {"confidence", "evidence_basis", "warnings", "manual_review_reasons"}.isdisjoint(
        {field.name for field in fields(type(record))}
    )
    result = discover_capabilities(
        RegistryReader(FIXTURES / "valid_registry.yml"), capability_id="alpha-reader"
    )[0]
    assert {"confidence", "evidence_basis", "warnings", "manual_review_reasons"} <= {
        field.name for field in fields(type(result))
    }


# --- RC4 validation models (#494) ------------------------------------------

from reusable_capability_registry.models import (  # noqa: E402
    EvidenceConfidence,
    ValidationEvidence,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
)


def _finding(code="path.missing", confidence=EvidenceConfidence.UNVERIFIED, severity=ValidationSeverity.FAIL,
             capability_id="alpha", surface="path", message="m", evidence=(), reason=None):
    return ValidationFinding(code, confidence, severity, capability_id, surface, message, evidence, reason)


def test_validation_models_are_frozen_and_slotted():
    evidence = ValidationEvidence("src/a.py", 3, "run", "python-ast", "detail")
    finding = _finding(evidence=(evidence,))
    for obj, field_name in ((evidence, "detail"), (finding, "message")):
        assert not hasattr(obj, "__dict__")
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field_name, "x")


def test_evidence_invariants():
    with pytest.raises(ValueError):
        ValidationEvidence("/abs.py", None, None, "s", "d")     # absolute path
    with pytest.raises(ValueError):
        ValidationEvidence("a.py", 0, None, "s", "d")           # non-positive line
    with pytest.raises(ValueError):
        ValidationEvidence(None, None, None, "", "d")           # empty source_type
    assert ValidationEvidence(None, None, None, "s", "d").path is None


def test_manual_review_reason_required_iff_manual_review():
    with pytest.raises(ValueError):
        _finding(severity=ValidationSeverity.MANUAL_REVIEW, reason=None)
    with pytest.raises(ValueError):
        _finding(severity=ValidationSeverity.FAIL, reason="not allowed")
    ok = _finding(severity=ValidationSeverity.MANUAL_REVIEW, reason="needs review")
    assert ok.manual_review_reason == "needs review"


def test_from_findings_derives_severity_orders_and_counts():
    empty = ValidationReport.from_findings([], provenance=None, capabilities_checked=2, checks_run=5)
    assert empty.severity is ValidationSeverity.PASS
    assert empty.report_version == "1.0"
    assert dict(empty.severity_counts) == {"fail": 0, "manual-review": 0, "pass": 0, "warn": 0}
    assert dict(empty.confidence_counts) == {
        "contradicted": 0, "manual-review": 0, "probable": 0, "unverified": 0, "verified": 0
    }

    warn = _finding(code="path.noncanonical", confidence=EvidenceConfidence.PROBABLE, severity=ValidationSeverity.WARN)
    fail = _finding(code="path.missing")
    report = ValidationReport.from_findings([warn, fail], provenance=None, capabilities_checked=1, checks_run=2)
    assert report.severity is ValidationSeverity.FAIL                    # fail > warn
    assert [f.code for f in report.findings] == ["path.missing", "path.noncanonical"]  # fail sorts first
    assert dict(report.severity_counts)["fail"] == 1 and dict(report.severity_counts)["warn"] == 1


def test_report_rejects_contradictory_severity():
    with pytest.raises(ValueError):
        ValidationReport("1.0", ValidationSeverity.PASS, None, 1, 1, (), (), (_finding(),), "notice")
    with pytest.raises(ValueError):
        ValidationReport("9.9", ValidationSeverity.PASS, None, 0, 0, (), (), (), "notice")


def test_evidence_is_sorted_within_findings():
    a = ValidationEvidence("z.py", None, None, "s", "d")
    b = ValidationEvidence("a.py", None, None, "s", "d")
    finding = _finding(evidence=(a, b))
    report = ValidationReport.from_findings([finding], provenance=None, capabilities_checked=1, checks_run=1)
    assert [e.path for e in report.findings[0].evidence] == ["a.py", "z.py"]
