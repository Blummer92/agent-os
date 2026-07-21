"""Focused tests for the informational reuse-evidence adapter (RC5B / #470).

Verifies the binding #248 contract (``#issuecomment-5035396385``): informational
reuse evidence may inform readiness but never determines it. Base readiness
outcome, ordinary checks, blockers, manual-review items, evidence, and exit codes
are invariant; only ``informational_checks`` is added.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.models import AcceptanceReport, CheckResult, Status
from scripts.agent_os_issue_acceptance.readiness import (
    ReadinessOutcome,
    ReadinessResult,
    evaluate_issue_readiness,
)
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
Removing a deprecation warning does not change documented behavior.
"""


# --- builders --------------------------------------------------------------


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


def _discovery(cap_id: str, confidence=Confidence.VERIFIED, provenance=PROV, **rec) -> DiscoveryResult:
    return DiscoveryResult(_record(cap_id, **rec), confidence, ("exact-capability-id-match",), (), (), provenance=provenance)


def _finding(cap_id, severity, confidence=EvidenceConfidence.VERIFIED, code="path.missing", reason=None) -> ValidationFinding:
    return ValidationFinding(
        code, confidence, severity, cap_id, "path", "message",
        (ValidationEvidence("src/a.py", 1, None, "python-ast", "detail"),), reason,
    )


def _report(findings=(), provenance=PROV) -> ValidationReport:
    return ValidationReport.from_findings(list(findings), provenance=provenance, capabilities_checked=3, checks_run=9)


def _base(body: str = "## Objective\nTier 0\n") -> ReadinessResult:
    return evaluate_issue_readiness(body)


def _informational(result: ReadinessResult):
    return [(c.name, c.status) for c in result.report.informational_checks]


# --- base readiness invariance ---------------------------------------------


def test_empty_discovery_returns_original_unchanged():
    base = _base()
    result = attach_reuse_evidence(base, [], _report())
    assert result is base
    assert base.report.informational_checks == ()


@pytest.mark.parametrize("confidence", list(Confidence))
def test_any_discovery_confidence_preserves_base_outcome_and_status(confidence):
    base = _base()
    result = attach_reuse_evidence(base, [_discovery("alpha", confidence=confidence)], _report())
    assert result.outcome == base.outcome
    assert result.report.overall_status == base.report.overall_status


def test_match_does_not_create_ready_and_no_match_does_not_create_blocked():
    # A blocked base stays blocked even with a clean verified match; a ready base
    # stays ready even when no discovery evidence matches cleanly.
    blocked = evaluate_issue_readiness("## Objective\nTier 0\nBlocked by: something\n")
    assert blocked.outcome == ReadinessOutcome.BLOCKED
    assert attach_reuse_evidence(blocked, [_discovery("alpha")], _report()).outcome == ReadinessOutcome.BLOCKED

    ready = _base(READY_BODY)
    assert ready.outcome == ReadinessOutcome.READY
    fail = attach_reuse_evidence(ready, [_discovery("alpha")], _report([_finding("alpha", ValidationSeverity.FAIL)]))
    assert fail.outcome == ReadinessOutcome.READY


def test_informational_manual_review_does_not_change_ready_outcome():
    ready = _base(READY_BODY)
    result = attach_reuse_evidence(ready, [_discovery("alpha", confidence=Confidence.PROBABLE)], _report())
    assert result.outcome == ReadinessOutcome.READY
    assert _informational(result)[0][1] is Status.MANUAL_REVIEW


def test_base_ordinary_fields_are_not_mutated_or_aliased():
    base = _base()
    checks_before = list(base.report.checks)
    blockers_before = list(base.report.blockers)
    manual_before = list(base.report.manual_review_items)
    result = attach_reuse_evidence(base, [_discovery("alpha")], _report([_finding("alpha", ValidationSeverity.FAIL)]))
    assert base.report.checks == checks_before
    assert base.report.blockers == blockers_before
    assert base.report.manual_review_items == manual_before
    assert base.report.informational_checks == ()
    # ordinary fields are shared-equal but never carry informational content
    assert result.report.checks == base.report.checks
    assert result.report.blockers == base.report.blockers
    assert result.report.manual_review_items == base.report.manual_review_items


# --- candidate classification ----------------------------------------------


def test_verified_clean_is_positive():
    result = attach_reuse_evidence(_base(), [_discovery("alpha")], _report())
    assert _informational(result) == [("reuse candidate alpha", Status.PASS)]


def test_verified_with_warning_is_qualified():
    report = _report([_finding("alpha", ValidationSeverity.WARN, EvidenceConfidence.PROBABLE, code="path.noncanonical")])
    result = attach_reuse_evidence(_base(), [_discovery("alpha")], report)
    assert _informational(result) == [("reuse candidate alpha", Status.WARN)]


@pytest.mark.parametrize("confidence", [Confidence.PROBABLE, Confidence.UNVERIFIED])
def test_probable_and_unverified_route_to_manual_review(confidence):
    result = attach_reuse_evidence(_base(), [_discovery("alpha", confidence=confidence)], _report())
    assert _informational(result) == [("reuse candidate alpha", Status.MANUAL_REVIEW)]


def test_rc4_manual_review_prevents_unqualified_recommendation():
    report = _report([_finding("alpha", ValidationSeverity.MANUAL_REVIEW, EvidenceConfidence.MANUAL_REVIEW, code="path.symlink-inside", reason="needs review")])
    result = attach_reuse_evidence(_base(), [_discovery("alpha")], report)
    assert _informational(result) == [("reuse candidate alpha", Status.MANUAL_REVIEW)]


def test_rc4_fail_suppresses_positive_but_keeps_evidence():
    report = _report([_finding("alpha", ValidationSeverity.FAIL)])
    result = attach_reuse_evidence(_base(), [_discovery("alpha")], report)
    check = result.report.informational_checks[0]
    assert check.status is Status.FAIL
    assert any("validation_finding=path.missing" in item for item in check.evidence)


def test_contradicted_evidence_suppresses_positive():
    report = _report([_finding("alpha", ValidationSeverity.WARN, EvidenceConfidence.CONTRADICTED, code="path.noncanonical")])
    result = attach_reuse_evidence(_base(), [_discovery("alpha")], report)
    assert result.report.informational_checks[0].status is Status.FAIL


def test_active_exemption_produces_explicit_warning_without_verified_consumer_claim():
    result = attach_reuse_evidence(_base(), [_discovery("alpha", known_consumer_exemption="temporary exemption")], _report())
    check = result.report.informational_checks[0]
    assert check.status is Status.WARN
    assert any("consumer_exemption=temporary exemption" in item for item in check.evidence)
    assert not any(item.startswith("known_consumer=") for item in check.evidence)


def test_missing_behavioral_evidence_appears_as_remaining_risk():
    result = attach_reuse_evidence(
        _base(), [_discovery("alpha", compatibility=(), invariants=())], _report()
    )
    check = result.report.informational_checks[0]
    assert any("remaining_risk=behavioral-contract-not-evaluated" in item for item in check.evidence)


@pytest.mark.parametrize("lifecycle", ["active", "experimental", "internal-only", "deprecated", "replaced"])
def test_lifecycle_states_are_represented_without_new_logic(lifecycle):
    result = attach_reuse_evidence(_base(), [_discovery("alpha", status=lifecycle)], _report())
    check = result.report.informational_checks[0]
    assert f"lifecycle_status={lifecycle}" in check.evidence


def test_unknown_finding_code_remains_visible_and_routes_to_manual_review():
    report = _report([_finding("alpha", ValidationSeverity.MANUAL_REVIEW, EvidenceConfidence.MANUAL_REVIEW, code="future.brand-new-code", reason="unknown")])
    result = attach_reuse_evidence(_base(), [_discovery("alpha")], report)
    check = result.report.informational_checks[0]
    assert check.status is Status.MANUAL_REVIEW
    assert any("validation_finding=future.brand-new-code" in item for item in check.evidence)


# --- multiple candidates ---------------------------------------------------


def test_multiple_candidates_are_preserved_and_sorted_by_capability_id():
    result = attach_reuse_evidence(_base(), [_discovery("gamma"), _discovery("alpha"), _discovery("beta")], _report())
    assert [name for name, _ in _informational(result)] == [
        "reuse candidate alpha",
        "reuse candidate beta",
        "reuse candidate gamma",
    ]


def test_identical_duplicate_candidates_collapse_to_one():
    disc = _discovery("alpha")
    result = attach_reuse_evidence(_base(), [disc, disc], _report())
    assert len(result.report.informational_checks) == 1


def test_conflicting_duplicates_fail_conservatively():
    result = attach_reuse_evidence(
        _base(),
        [_discovery("alpha"), _discovery("alpha", confidence=Confidence.PROBABLE)],
        _report(),
    )
    checks = result.report.informational_checks
    assert len(checks) == 1
    assert checks[0].status is Status.MANUAL_REVIEW
    assert any("conflicting_discovery_results=2" in item for item in checks[0].evidence)


# --- provenance and unmatched findings -------------------------------------


def test_matching_provenance_permits_positive_guidance():
    assert attach_reuse_evidence(_base(), [_discovery("alpha")], _report()).report.informational_checks[0].status is Status.PASS


@pytest.mark.parametrize(
    "discovery_prov,report_prov,label",
    [
        (OTHER_PROV, PROV, "mismatch"),
        (None, PROV, "missing"),
        (PROV, None, "missing"),
        (UNSUPPORTED_PROV, UNSUPPORTED_PROV, "unsupported"),
    ],
)
def test_provenance_failures_suppress_positive_conservatively(discovery_prov, report_prov, label):
    base = _base()
    result = attach_reuse_evidence(base, [_discovery("alpha", provenance=discovery_prov)], _report(provenance=report_prov))
    check = result.report.informational_checks[0]
    assert check.status is Status.MANUAL_REVIEW
    assert f"provenance={label}" in check.evidence
    assert result.outcome == base.outcome


def test_findings_for_absent_capability_do_not_attach_to_another_candidate():
    report = _report([_finding("zeta", ValidationSeverity.FAIL)])
    result = attach_reuse_evidence(_base(), [_discovery("alpha")], report)
    names = [name for name, _ in _informational(result)]
    assert names == ["reuse candidate alpha", "reuse unmatched validation findings"]
    # the alpha candidate is clean (no finding leaked onto it)
    assert result.report.informational_checks[0].status is Status.PASS
    unmatched = result.report.informational_checks[1]
    assert any("capability_id=zeta" in item for item in unmatched.evidence)


def test_finding_with_null_capability_id_is_unmatched():
    report = _report([_finding(None, ValidationSeverity.FAIL, code="structure.malformed-registry")])
    result = attach_reuse_evidence(_base(), [_discovery("alpha")], report)
    unmatched = result.report.informational_checks[-1]
    assert unmatched.name == "reuse unmatched validation findings"
    assert any("capability_id=none" in item for item in unmatched.evidence)


# --- malformed input -------------------------------------------------------


def test_non_iterable_discovery_returns_error_entry():
    base = _base()
    result = attach_reuse_evidence(base, 123, _report())  # type: ignore[arg-type]
    assert _informational(result) == [("reuse-evidence-error", Status.MANUAL_REVIEW)]
    assert result.outcome == base.outcome
    assert result.report.blockers == base.report.blockers  # base blockers unchanged


def test_malformed_discovery_element_returns_error_entry():
    result = attach_reuse_evidence(_base(), ["not-a-discovery-result"], _report())  # type: ignore[list-item]
    assert _informational(result) == [("reuse-evidence-error", Status.MANUAL_REVIEW)]


def test_malformed_validation_report_returns_error_entry():
    result = attach_reuse_evidence(_base(), [_discovery("alpha")], "not-a-report")  # type: ignore[arg-type]
    assert _informational(result) == [("reuse-evidence-error", Status.MANUAL_REVIEW)]


# --- determinism and mutation safety ---------------------------------------


def test_repeated_calls_return_equal_results():
    base = _base()
    args = ([_discovery("alpha"), _discovery("beta")], _report([_finding("alpha", ValidationSeverity.WARN, EvidenceConfidence.PROBABLE, code="path.noncanonical")]))
    first = attach_reuse_evidence(base, *args)
    second = attach_reuse_evidence(base, *args)
    assert render_report(first.report) == render_report(second.report)


def test_output_is_invariant_under_input_order():
    base = _base()
    report = _report([_finding("beta", ValidationSeverity.FAIL), _finding("alpha", ValidationSeverity.WARN, EvidenceConfidence.PROBABLE, code="path.noncanonical")])
    forward = attach_reuse_evidence(base, [_discovery("alpha"), _discovery("beta")], report)
    reverse = attach_reuse_evidence(base, [_discovery("beta"), _discovery("alpha")], report)
    assert render_report(forward.report) == render_report(reverse.report)


def test_inputs_are_not_mutated():
    base = _base()
    discovery = [_discovery("alpha")]
    report = _report([_finding("alpha", ValidationSeverity.WARN, EvidenceConfidence.PROBABLE, code="path.noncanonical")])
    findings_before = report.findings
    attach_reuse_evidence(base, discovery, report)
    assert len(discovery) == 1
    assert report.findings == findings_before


# --- report compatibility --------------------------------------------------


def test_legacy_render_is_byte_for_byte_unchanged_when_empty():
    base = _base()
    augmented = attach_reuse_evidence(base, [], _report())
    assert render_report(augmented.report) == render_report(base.report)
    assert "Reusable-capability evidence" not in render_report(base.report)


def test_informational_section_is_appended_after_remaining_risks():
    result = attach_reuse_evidence(_base(), [_discovery("alpha")], _report())
    rendered = render_report(result.report)
    assert rendered.index("Remaining risks:") < rendered.index("Reusable-capability evidence (informational):")
    assert rendered.endswith("\n") and not rendered.endswith("\n\n")


def test_informational_checks_do_not_enter_ordinary_checks_block():
    result = attach_reuse_evidence(_base(), [_discovery("alpha")], _report())
    rendered = render_report(result.report)
    checks_block = rendered.split("Manual review items:")[0]
    assert "reuse candidate alpha" not in checks_block


def test_exit_code_is_unaffected_by_informational_content():
    base = _base(READY_BODY)
    result = attach_reuse_evidence(base, [_discovery("alpha")], _report([_finding("alpha", ValidationSeverity.FAIL)]))
    assert exit_code_for(result.report.overall_status) == exit_code_for(base.report.overall_status)


def test_non_ascii_evidence_renders_faithfully_without_normalization():
    result = attach_reuse_evidence(_base(), [_discovery("alpha", reuse_guidance="rëuse café ①")], _report())
    assert "rëuse café ①" in render_report(result.report)


def test_label_json_projection_is_byte_stable_regardless_of_informational_content():
    from scripts.agent_os_issue_labels.report import render_json, report_to_dict

    base = _base()
    augmented = attach_reuse_evidence(base, [_discovery("alpha")], _report())
    assert report_to_dict(augmented.report) == report_to_dict(base.report)
    assert render_json(augmented.report) == render_json(base.report)
    assert "informational" not in render_json(augmented.report)


# --- dependency isolation --------------------------------------------------


def test_base_readiness_imports_without_registry_package_in_separate_process():
    code = (
        "import sys\n"
        "BLOCK='reusable_capability_registry'\n"
        "for k in [m for m in list(sys.modules) if m==BLOCK or m.startswith(BLOCK+'.')]: del sys.modules[k]\n"
        "sys.modules[BLOCK]=None\n"
        "try:\n"
        "    import reusable_capability_registry\n"
        "    raise SystemExit('registry import should have failed')\n"
        "except ImportError:\n"
        "    pass\n"
        "import scripts.agent_os_issue_acceptance\n"
        "import scripts.agent_os_issue_acceptance.readiness as r\n"
        "res=r.evaluate_issue_readiness('## Objective\\nTier 0\\n')\n"
        "assert res.outcome is not None\n"
        "print('ok')\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_adapter_use_does_not_import_registry_cli_or_entry_points():
    # Using the adapter must never pull the registry CLI / entry points into the process.
    attach_reuse_evidence(_base(), [_discovery("alpha")], _report())
    assert "reusable_capability_registry.cli" not in sys.modules
    assert "reusable_capability_registry.__main__" not in sys.modules


def test_adapter_is_not_exported_from_package_facade():
    import scripts.agent_os_issue_acceptance as pkg

    assert not hasattr(pkg, "attach_reuse_evidence")
