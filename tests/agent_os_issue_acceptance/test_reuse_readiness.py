"""Focused tests for the informational reuse-evidence adapter."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_acceptance.readiness import ReadinessOutcome, ReadinessResult, evaluate_issue_readiness
from scripts.agent_os_issue_acceptance.report import exit_code_for, render_report
from scripts.agent_os_issue_acceptance.reuse_readiness import attach_reuse_evidence
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

REPO_ROOT = Path(__file__).resolve().parents[2]
PROV = RegistryProvenance("registry-canonical-records", 1, "0.1.0", "a" * 64)
OTHER_PROV = RegistryProvenance("registry-canonical-records", 1, "0.1.0", "b" * 64)
UNSUPPORTED_PROV = RegistryProvenance("registry-canonical-records", 2, "0.1.0", "a" * 64)
READY_BODY = """
Issue Tier: 0
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


def _record(cap_id: str, **overrides) -> CapabilityRecord:
    data = dict(
        capability_id=cap_id,
        name="Name",
        summary="Summary",
        status="active",
        canonical_paths=("src/a.py",),
        public_interfaces=("src.a:run",),
        owner_agent="Integration Manager",
        supporting_agents=(),
        known_consumers=("scripts/consumer.py",),
        known_consumer_exemption=None,
        tests=("tests/test_a.py",),
        keywords=("a",),
        reuse_guidance="Reuse a.",
        side_effects=("none",),
        invariants=("deterministic",),
        compatibility=("stable",),
    )
    data.update(overrides)
    return CapabilityRecord(**data)


def _discovery(
    cap_id: str,
    confidence: Confidence = Confidence.VERIFIED,
    provenance: RegistryProvenance | None = PROV,
    evidence_basis: tuple[str, ...] = ("exact-capability-id-match",),
    warnings: tuple[str, ...] = (),
    manual_review_reasons: tuple[str, ...] = (),
    **record_overrides,
) -> DiscoveryResult:
    return DiscoveryResult(
        _record(cap_id, **record_overrides),
        confidence,
        evidence_basis,
        warnings,
        manual_review_reasons,
        provenance=provenance,
    )


def _finding(
    cap_id: str | None,
    severity: ValidationSeverity,
    confidence: EvidenceConfidence = EvidenceConfidence.VERIFIED,
    code: str = "path.missing",
    reason: str | None = None,
    message: str = "message",
    evidence: tuple[ValidationEvidence, ...] | None = None,
) -> ValidationFinding:
    if evidence is None:
        evidence = (ValidationEvidence("src/a.py", 1, None, "python-ast", "detail"),)
    return ValidationFinding(code, confidence, severity, cap_id, "path", message, evidence, reason)


def _report(findings=(), provenance=PROV) -> ValidationReport:
    return ValidationReport.from_findings(
        list(findings), provenance=provenance, capabilities_checked=3, checks_run=9
    )


def _base(body: str = "## Objective\nTier 0\n") -> ReadinessResult:
    return evaluate_issue_readiness(body)


def _info(result: ReadinessResult):
    return [(x.name, x.status) for x in result.report.informational_checks]


def test_empty_discovery_returns_original_identity():
    base = _base()
    assert attach_reuse_evidence(base, [], _report()) is base


@pytest.mark.parametrize("confidence", list(Confidence))
def test_discovery_confidence_never_changes_readiness(confidence):
    base = _base()
    result = attach_reuse_evidence(base, [_discovery("alpha", confidence)], _report())
    assert result.outcome == base.outcome
    assert result.report.overall_status == base.report.overall_status


def test_ready_and_blocked_outcomes_are_invariant():
    blocked = evaluate_issue_readiness("## Objective\nTier 0\nBlocked by: dependency\n")
    assert blocked.outcome is ReadinessOutcome.BLOCKED
    assert attach_reuse_evidence(blocked, [_discovery("alpha")], _report()).outcome is ReadinessOutcome.BLOCKED
    ready = _base(READY_BODY)
    assert ready.outcome is ReadinessOutcome.READY
    report = _report([_finding("alpha", ValidationSeverity.FAIL)])
    assert attach_reuse_evidence(ready, [_discovery("alpha")], report).outcome is ReadinessOutcome.READY


def test_augmented_report_lists_are_equal_but_independent():
    base = _base()
    result = attach_reuse_evidence(base, [_discovery("alpha")], _report())
    for name in ("checks", "manual_review_items", "evidence", "blockers", "remaining_risks"):
        assert getattr(result.report, name) == getattr(base.report, name)
        assert getattr(result.report, name) is not getattr(base.report, name)
    for old, new in zip(base.report.checks, result.report.checks):
        assert new is not old
        assert new.evidence == old.evidence
        assert new.evidence is not old.evidence


def test_report_list_mutations_do_not_cross_alias_boundary():
    base = _base()
    result = attach_reuse_evidence(base, [_discovery("alpha")], _report())
    result.report.blockers.append("augmented-only")
    base.report.remaining_risks.append("base-only")
    assert "augmented-only" not in base.report.blockers
    assert "base-only" not in result.report.remaining_risks


@pytest.mark.parametrize(
    "confidence,findings,expected",
    [
        (Confidence.VERIFIED, (), Status.PASS),
        (Confidence.PROBABLE, (), Status.MANUAL_REVIEW),
        (Confidence.UNVERIFIED, (), Status.MANUAL_REVIEW),
        (Confidence.VERIFIED, (_finding("alpha", ValidationSeverity.WARN),), Status.WARN),
        (Confidence.VERIFIED, (_finding("alpha", ValidationSeverity.MANUAL_REVIEW, EvidenceConfidence.MANUAL_REVIEW, reason="review"),), Status.MANUAL_REVIEW),
        (Confidence.VERIFIED, (_finding("alpha", ValidationSeverity.FAIL),), Status.FAIL),
        (Confidence.VERIFIED, (_finding("alpha", ValidationSeverity.WARN, EvidenceConfidence.CONTRADICTED),), Status.FAIL),
    ],
)
def test_candidate_classification(confidence, findings, expected):
    result = attach_reuse_evidence(_base(), [_discovery("alpha", confidence)], _report(findings))
    assert result.report.informational_checks[0].status is expected


def test_exemption_and_missing_behavioral_contract_are_visible():
    exempt = attach_reuse_evidence(
        _base(), [_discovery("alpha", known_consumer_exemption="temporary")], _report()
    ).report.informational_checks[0]
    assert exempt.status is Status.WARN
    assert "consumer_exemption=temporary" in exempt.evidence
    no_contract = attach_reuse_evidence(
        _base(), [_discovery("alpha", compatibility=(), invariants=())], _report()
    ).report.informational_checks[0]
    assert "remaining_risk=behavioral-contract-not-evaluated" in no_contract.evidence


@pytest.mark.parametrize("state", ["active", "experimental", "internal-only", "deprecated", "replaced"])
def test_lifecycle_state_is_preserved(state):
    check = attach_reuse_evidence(
        _base(), [_discovery("alpha", status=state)], _report()
    ).report.informational_checks[0]
    assert f"lifecycle_status={state}" in check.evidence


def test_matched_finding_preserves_complete_evidence():
    evidence = (
        ValidationEvidence("src/b.py", 8, "pkg.mod:run", "python-ast", "second"),
        ValidationEvidence("src/a.py", 2, None, "filesystem", "first"),
    )
    finding = _finding(
        "alpha",
        ValidationSeverity.MANUAL_REVIEW,
        EvidenceConfidence.MANUAL_REVIEW,
        code="future.code",
        reason="human reason",
        message="full message",
        evidence=evidence,
    )
    check = attach_reuse_evidence(_base(), [_discovery("alpha")], _report([finding])).report.informational_checks[0]
    rendered = "\n".join(check.evidence)
    for value in (
        "validation_finding=future.code",
        "capability_id=alpha",
        "surface=path",
        "severity=manual-review",
        "confidence=manual-review",
        "message=full message",
        "manual_review_reason=human reason",
        "path=src/a.py; line=2; symbol=none; source_type=filesystem; detail=first",
        "path=src/b.py; line=8; symbol=pkg.mod:run; source_type=python-ast; detail=second",
    ):
        assert value in rendered
    assert rendered.index("path=src/a.py") < rendered.index("path=src/b.py")


def test_unmatched_finding_preserves_complete_evidence():
    finding = _finding(None, ValidationSeverity.FAIL, code="structure.bad", message="broken")
    result = attach_reuse_evidence(_base(), [_discovery("alpha")], _report([finding]))
    rendered = "\n".join(result.report.informational_checks[-1].evidence)
    assert "capability_id=none" in rendered
    assert "message=broken" in rendered
    assert "source_type=python-ast" in rendered


def test_unmatched_findings_are_deterministic():
    a = _finding("zeta", ValidationSeverity.WARN, code="z.code")
    b = _finding(None, ValidationSeverity.FAIL, code="a.code")
    forward = attach_reuse_evidence(_base(), [_discovery("alpha")], _report([a, b]))
    reverse = attach_reuse_evidence(_base(), [_discovery("alpha")], _report([b, a]))
    assert render_report(forward.report) == render_report(reverse.report)


def test_multiple_candidates_sort_and_identical_duplicates_collapse():
    result = attach_reuse_evidence(
        _base(), [_discovery("gamma"), _discovery("alpha"), _discovery("beta")], _report()
    )
    assert [x.name for x in result.report.informational_checks] == [
        "reuse candidate alpha", "reuse candidate beta", "reuse candidate gamma"
    ]
    same = _discovery("alpha")
    assert len(attach_reuse_evidence(_base(), [same, same], _report()).report.informational_checks) == 1


def test_conflicting_variants_preserve_all_material_details_and_order():
    first = _discovery(
        "alpha",
        Confidence.VERIFIED,
        PROV,
        evidence_basis=("first-basis",),
        warnings=("first-warning",),
        manual_review_reasons=("first-review",),
        summary="First summary",
    )
    second = _discovery(
        "alpha",
        Confidence.PROBABLE,
        OTHER_PROV,
        evidence_basis=("second-basis",),
        warnings=("second-warning",),
        manual_review_reasons=("second-review",),
        summary="Second summary",
    )
    forward = attach_reuse_evidence(_base(), [first, second], _report())
    reverse = attach_reuse_evidence(_base(), [second, first], _report())
    assert render_report(forward.report) == render_report(reverse.report)
    check = forward.report.informational_checks[0]
    assert check.status is Status.MANUAL_REVIEW
    rendered = "\n".join(check.evidence)
    for value in (
        "first-basis", "second-basis", "first-warning", "second-warning",
        "first-review", "second-review", PROV.digest, OTHER_PROV.digest,
        "capability_summary='First summary'", "capability_summary='Second summary'",
    ):
        assert value in rendered


@pytest.mark.parametrize(
    "discovery_prov,report_prov,label",
    [(OTHER_PROV, PROV, "mismatch"), (None, PROV, "missing"), (PROV, None, "missing"), (UNSUPPORTED_PROV, UNSUPPORTED_PROV, "unsupported")],
)
def test_provenance_failures_suppress_positive(discovery_prov, report_prov, label):
    check = attach_reuse_evidence(
        _base(), [_discovery("alpha", provenance=discovery_prov)], _report(provenance=report_prov)
    ).report.informational_checks[0]
    assert check.status is Status.MANUAL_REVIEW
    assert f"provenance={label}" in check.evidence


@pytest.mark.parametrize(
    "discovery,report",
    [(123, _report()), (["bad"], _report()), ([_discovery("alpha")], "bad")],
)
def test_known_malformed_inputs_return_one_error(discovery, report):
    result = attach_reuse_evidence(_base(), discovery, report)  # type: ignore[arg-type]
    assert _info(result) == [("reuse-evidence-error", Status.MANUAL_REVIEW)]
    assert len(result.report.informational_checks) == 1


def test_malformed_provenance_returns_error():
    malformed = object.__new__(DiscoveryResult)
    object.__setattr__(malformed, "capability", _record("alpha"))
    object.__setattr__(malformed, "confidence", Confidence.VERIFIED)
    object.__setattr__(malformed, "evidence_basis", ())
    object.__setattr__(malformed, "warnings", ())
    object.__setattr__(malformed, "manual_review_reasons", ())
    object.__setattr__(malformed, "provenance", "bad")
    assert _info(attach_reuse_evidence(_base(), [malformed], _report())) == [
        ("reuse-evidence-error", Status.MANUAL_REVIEW)
    ]


def test_unexpected_programmer_defect_is_not_swallowed(monkeypatch):
    import scripts.agent_os_issue_acceptance.reuse_readiness as module

    monkeypatch.setattr(module, "_checks", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        attach_reuse_evidence(_base(), [_discovery("alpha")], _report())


def test_render_exit_code_label_projection_and_input_order_regressions():
    base = _base(READY_BODY)
    empty = attach_reuse_evidence(base, [], _report())
    assert render_report(empty.report) == render_report(base.report)
    fail = attach_reuse_evidence(base, [_discovery("alpha")], _report([_finding("alpha", ValidationSeverity.FAIL)]))
    assert exit_code_for(fail.report.overall_status) == exit_code_for(base.report.overall_status)
    from scripts.agent_os_issue_labels.report import render_json, report_to_dict

    assert report_to_dict(fail.report) == report_to_dict(base.report)
    assert render_json(fail.report) == render_json(base.report)
    forward = attach_reuse_evidence(_base(), [_discovery("beta"), _discovery("alpha")], _report())
    reverse = attach_reuse_evidence(_base(), [_discovery("alpha"), _discovery("beta")], _report())
    assert render_report(forward.report) == render_report(reverse.report)


def test_inputs_are_not_mutated():
    discovery = [_discovery("alpha")]
    report = _report([_finding("alpha", ValidationSeverity.WARN)])
    findings = report.findings
    attach_reuse_evidence(_base(), discovery, report)
    assert len(discovery) == 1
    assert report.findings == findings


def test_base_readiness_imports_without_registry_package_in_separate_process():
    code = (
        "import sys\n"
        "BLOCK='reusable_capability_registry'\n"
        "for k in [m for m in list(sys.modules) if m==BLOCK or m.startswith(BLOCK+'.')]: del sys.modules[k]\n"
        "sys.modules[BLOCK]=None\n"
        "import scripts.agent_os_issue_acceptance.readiness as r\n"
        "assert r.evaluate_issue_readiness('## Objective\\nTier 0\\n').outcome is not None\n"
        "print('ok')\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_adapter_does_not_import_registry_cli_or_export_from_facade():
    attach_reuse_evidence(_base(), [_discovery("alpha")], _report())
    assert "reusable_capability_registry.cli" not in sys.modules
    assert "reusable_capability_registry.__main__" not in sys.modules
    import scripts.agent_os_issue_acceptance as package

    assert not hasattr(package, "attach_reuse_evidence")
