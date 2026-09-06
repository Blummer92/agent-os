"""RC6-A adversarial validation for the reusable-capability evidence boundary.

This suite replaces mechanically testable portions of the unavailable three-person
RC6 pilot. It does not simulate participants or claim independent-user evidence.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_acceptance.readiness import ReadinessOutcome, evaluate_issue_readiness
from scripts.agent_os_issue_acceptance.report import render_report
from scripts.agent_os_issue_acceptance.reuse_readiness import attach_reuse_evidence
from reusable_capability_registry.models import (
    CapabilityRecord,
    Confidence,
    DiscoveryResult,
    EvidenceConfidence,
    RegistryProvenance,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
)

PROV = RegistryProvenance("registry-canonical-records", 1, "0.1.0", "a" * 64)
OTHER_PROV = replace(PROV, digest="b" * 64)
AUTH_LINE = "authorization=evidence-only-not-implementation-write-or-merge"


def record(capability_id: str, **overrides) -> CapabilityRecord:
    values = dict(
        capability_id=capability_id,
        name="RC6 fixture capability",
        summary="Adversarial fixture",
        status="active",
        canonical_paths=("src/example.py",),
        public_interfaces=("src.example:run",),
        owner_agent="GitHub Service Agent",
        supporting_agents=(),
        known_consumers=("scripts/consumer.py",),
        known_consumer_exemption=None,
        tests=("tests/test_example.py",),
        keywords=("fixture",),
        reuse_guidance="Reuse only after independent authorization.",
        side_effects=("none",),
        invariants=("deterministic",),
        compatibility=("stable",),
    )
    values.update(overrides)
    return CapabilityRecord(**values)


def discovery(capability_id: str, *, confidence=Confidence.VERIFIED, provenance=PROV, **overrides):
    return DiscoveryResult(
        record(capability_id, **overrides), confidence,
        ("rc6-adversarial-fixture",), (), (), provenance=provenance,
    )


def finding(capability_id: str | None, severity: ValidationSeverity, *, confidence=EvidenceConfidence.VERIFIED):
    return ValidationFinding(
        "rc6.fixture", confidence, severity, capability_id, "fixture",
        "adversarial validation finding", (), None,
    )


def report(*findings_: ValidationFinding, provenance=PROV):
    return ValidationReport.from_findings(
        list(findings_), provenance=provenance, capabilities_checked=1, checks_run=1
    )


def base(body: str = "## Objective\nTier 0\n"):
    return evaluate_issue_readiness(body)


def check(result):
    return result.report.informational_checks[0]


def assert_evidence_only(result):
    assert all(AUTH_LINE in item.evidence for item in result.report.informational_checks)


@pytest.mark.parametrize(
    "body,expected",
    [
        ("## Objective\nTier 0\n", ReadinessOutcome.NEEDS_DECISION),
        ("## Objective\nTier 0\nBlocked by: dependency\n", ReadinessOutcome.BLOCKED),
    ],
)
def test_reuse_evidence_never_changes_base_readiness(body, expected):
    original = base(body)
    assert original.outcome is expected
    augmented = attach_reuse_evidence(original, [discovery("alpha")], report())
    assert augmented.outcome is expected
    assert augmented.report.overall_status == original.report.overall_status
    assert_evidence_only(augmented)


def test_manual_review_is_informational_not_needs_decision():
    original = base()
    augmented = attach_reuse_evidence(
        original, [discovery("alpha", confidence=Confidence.PROBABLE)], report()
    )
    assert augmented.outcome is original.outcome
    assert check(augmented).status is Status.MANUAL_REVIEW
    assert "informational manual-review advisory" in check(augmented).message
    assert_evidence_only(augmented)


def test_provenance_match_is_identity_evidence_not_authorization():
    augmented = attach_reuse_evidence(base(), [discovery("alpha")], report())
    item = check(augmented)
    assert "provenance=matched" in item.evidence
    assert AUTH_LINE in item.evidence
    assert not any("authorization=true" in line for line in item.evidence)


def test_provenance_mismatch_suppresses_positive_guidance():
    augmented = attach_reuse_evidence(
        base(), [discovery("alpha", provenance=OTHER_PROV)], report(provenance=PROV)
    )
    item = check(augmented)
    assert item.status is Status.MANUAL_REVIEW
    assert "provenance=mismatch" in item.evidence
    assert "positive reuse guidance is suppressed" in item.message
    assert AUTH_LINE in item.evidence


def test_multiple_distinct_candidates_are_sorted_not_auto_selected():
    augmented = attach_reuse_evidence(
        base(), [discovery("beta"), discovery("alpha")], report()
    )
    assert [item.name for item in augmented.report.informational_checks] == [
        "reuse candidate alpha", "reuse candidate beta"
    ]
    assert len(augmented.report.informational_checks) == 2
    assert_evidence_only(augmented)


def test_conflicting_same_id_candidates_fail_safe_to_manual_review():
    first = discovery("alpha", summary="first")
    second = discovery("alpha", summary="second")
    augmented = attach_reuse_evidence(base(), [first, second], report())
    item = check(augmented)
    assert item.status is Status.MANUAL_REVIEW
    assert "multiple conflicting discovery results" in item.message
    assert AUTH_LINE in item.evidence


def test_no_match_does_not_manufacture_reuse_evidence():
    original = base()
    augmented = attach_reuse_evidence(original, [], report())
    assert augmented is original
    assert not augmented.report.informational_checks


def test_malformed_evidence_fails_safe_without_readiness_mutation():
    original = base()
    augmented = attach_reuse_evidence(original, ["not-a-discovery-result"], report())  # type: ignore[list-item]
    assert augmented.outcome is original.outcome
    assert check(augmented).name == "reuse-evidence-error"
    assert check(augmented).status is Status.MANUAL_REVIEW


def test_contradicted_validation_suppresses_positive_guidance():
    augmented = attach_reuse_evidence(
        base(), [discovery("alpha")],
        report(finding("alpha", ValidationSeverity.WARN, confidence=EvidenceConfidence.CONTRADICTED)),
    )
    item = check(augmented)
    assert item.status is Status.FAIL
    assert "positive reuse guidance is suppressed" in item.message
    assert AUTH_LINE in item.evidence


def test_active_exemption_is_visible_and_qualified():
    augmented = attach_reuse_evidence(
        base(), [discovery("alpha", known_consumers=(), known_consumer_exemption="temporary")], report()
    )
    item = check(augmented)
    assert item.status is Status.WARN
    assert "consumer_exemption=temporary" in item.evidence
    assert "no verified-consumer claim" in item.message
    assert AUTH_LINE in item.evidence


def test_output_is_deterministic_for_input_order():
    forward = attach_reuse_evidence(base(), [discovery("beta"), discovery("alpha")], report())
    reverse = attach_reuse_evidence(base(), [discovery("alpha"), discovery("beta")], report())
    assert render_report(forward.report) == render_report(reverse.report)


def test_authorization_error_rates_are_zero_across_adversarial_cases():
    cases = [
        attach_reuse_evidence(base(), [discovery("clean")], report()),
        attach_reuse_evidence(base(), [discovery("probable", confidence=Confidence.PROBABLE)], report()),
        attach_reuse_evidence(base(), [discovery("mismatch", provenance=OTHER_PROV)], report()),
        attach_reuse_evidence(
            base(), [discovery("contradicted")],
            report(finding("contradicted", ValidationSeverity.WARN, confidence=EvidenceConfidence.CONTRADICTED)),
        ),
    ]
    implementation_false_authorized = 0
    merge_false_authorized = 0
    for result in cases:
        assert_evidence_only(result)
        rendered = render_report(result.report)
        implementation_false_authorized += int("implementation-authorized=true" in rendered)
        merge_false_authorized += int("merge-authorized=true" in rendered)
    assert implementation_false_authorized == 0
    assert merge_false_authorized == 0
