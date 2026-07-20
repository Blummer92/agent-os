from dataclasses import FrozenInstanceError, replace

import pytest

from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION,
    IssuePlanCurrentStateOutcome,
    build_issueplan_current_state_evidence,
    compare_issueplan_current_state,
    compute_issueplan_current_state_fingerprint,
)
from scripts.agent_os_issue_acceptance.issueplan_scanner import (
    AdoptionClass,
    MetadataCandidate,
    ScanFinding,
    ScanResult,
    SourceEnvelope,
)


def _scan_result(
    *,
    source_revision: str = "rev-1",
    candidates: tuple[MetadataCandidate, ...] | None = None,
    findings: tuple[ScanFinding, ...] = (),
) -> ScanResult:
    if candidates is None:
        candidates = (
            MetadataCandidate(
                1,
                "raw",
                {
                    "profile_version": "issueplan-core/v1",
                    "entity_id": "issue-360",
                    "revision": "candidate-1",
                    "owner_agent": "Integration Manager",
                },
            ),
        )
    return ScanResult(
        source_locator="github:Blummer92/agent-os#360",
        source_revision=source_revision,
        findings=findings,
        adoption_class=AdoptionClass.STRICT_NATIVE,
        candidates=candidates,
        strict_valid=True,
        execution_authorized=False,
        evidence=("bounded=true",),
    )


def _build(
    *,
    source_revision: str = "rev-1",
    content: str = "issue body",
    scan_result: ScanResult | None = None,
    contract: dict | None = None,
    schema_version: str = ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION,
    retrieval_complete: bool = True,
    pagination_complete: bool = True,
    accessible: bool = True,
    source_family: str = "github-issue",
    projection_complete: bool = True,
    projection_lookup_succeeded: bool = True,
    freshness_boundary: str = "main@abc123",
):
    result = scan_result or _scan_result(source_revision=source_revision)
    envelope = SourceEnvelope(
        source_locator="github:Blummer92/agent-os#360",
        source_revision=source_revision,
        content=content,
        retrieval_complete=retrieval_complete,
        pagination_complete=pagination_complete,
        accessible=accessible,
        source_family=source_family,
    )
    evidence = build_issueplan_current_state_evidence(
        envelope=envelope,
        scan_result=result,
        observed_at="2026-07-20T01:00:00Z",
        freshness_boundary=freshness_boundary,
        implementation_contract=contract
        or {
            "scope": ("current-state evidence",),
            "allowlist": ("issueplan_current_state.py",),
            "required_tests": ("test_issueplan_current_state.py",),
        },
        governed_field_names=("absent_field", "null_field"),
        intentionally_omitted_fields=("omitted_field",),
        unavailable_fields=("unavailable_field",),
        graph_reference="graph-digest",
        planning_result_reference="planning-digest",
        handoff_reference="handoff-digest",
        projection_complete=projection_complete,
        projection_lookup_succeeded=projection_lookup_succeeded,
        schema_version=schema_version,
    )
    return evidence, result


def test_identical_inputs_are_deterministic_current_and_never_authorized():
    first, result = _build()
    second, _ = _build()

    assert first == second
    assert first.execution_authorized is False
    comparison = compare_issueplan_current_state(
        first, second, current_scan_result=result
    )
    assert comparison.outcome == IssuePlanCurrentStateOutcome.CURRENT
    assert comparison.reason_codes == ()
    assert comparison.execution_authorized is False


def test_models_are_frozen():
    evidence, _ = _build()
    with pytest.raises(FrozenInstanceError):
        evidence.evidence_id = "changed"
    with pytest.raises(FrozenInstanceError):
        evidence.source.source_revision = "changed"


def test_complete_candidate_set_contributes_to_evidence_identity():
    first, _ = _build()
    candidates = (
        MetadataCandidate(1, "raw", {"entity_id": "issue-360"}),
        MetadataCandidate(2, "other", {"entity_id": "issue-360"}),
    )
    result = _scan_result(
        candidates=candidates,
        findings=(ScanFinding.METADATA_DUPLICATED_IDENTICAL,),
    )
    current, _ = _build(scan_result=result)

    comparison = compare_issueplan_current_state(
        first, current, current_scan_result=result
    )
    assert comparison.outcome == IssuePlanCurrentStateOutcome.BLOCKED
    assert "candidate.changed" in comparison.reason_codes
    assert "scanner.multiple-identical" in comparison.reason_codes


def test_source_revision_change_is_stale():
    expected, _ = _build()
    current_result = _scan_result(source_revision="rev-2")
    current, _ = _build(source_revision="rev-2", scan_result=current_result)

    comparison = compare_issueplan_current_state(
        expected, current, current_scan_result=current_result
    )
    assert comparison.outcome == IssuePlanCurrentStateOutcome.STALE
    assert "source.revision-changed" in comparison.reason_codes


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"retrieval_complete": False}, "source.partial"),
        ({"pagination_complete": False}, "source.unknown-pagination"),
        ({"accessible": False}, "source.inaccessible"),
        ({"source_family": "unsupported"}, "source.unsupported"),
        ({"projection_complete": False}, "projection.incomplete"),
        (
            {"projection_lookup_succeeded": False},
            "projection.lookup-failed",
        ),
    ],
)
def test_incomplete_or_unsupported_evidence_fails_closed(kwargs, reason):
    expected, _ = _build()
    current, result = _build(**kwargs)

    comparison = compare_issueplan_current_state(
        expected, current, current_scan_result=result
    )
    assert comparison.outcome == IssuePlanCurrentStateOutcome.BLOCKED
    assert reason in comparison.reason_codes


@pytest.mark.parametrize(
    ("finding", "reason"),
    [
        (
            ScanFinding.METADATA_DUPLICATED_IDENTICAL,
            "scanner.multiple-identical",
        ),
        (ScanFinding.METADATA_CONFLICTING, "scanner.multiple-conflicting"),
        (ScanFinding.METADATA_MALFORMED, "scanner.malformed-candidate"),
        (
            ScanFinding.UNKNOWN_GOVERNED_FIELD,
            "scanner.unknown-governed-field",
        ),
        (ScanFinding.IDENTITY_FINDING_PRESENT, "identity.quarantined"),
    ],
)
def test_scanner_findings_use_bounded_reason_codes(finding, reason):
    expected, _ = _build()
    current_result = _scan_result(findings=(finding,))
    current, _ = _build(scan_result=current_result)

    comparison = compare_issueplan_current_state(
        expected, current, current_scan_result=current_result
    )
    assert comparison.outcome == IssuePlanCurrentStateOutcome.BLOCKED
    assert reason in comparison.reason_codes


def test_contract_changes_have_specific_reason_codes():
    expected, _ = _build()
    current, result = _build(
        contract={
            "scope": ("changed",),
            "allowlist": ("other.py",),
            "required_tests": ("other_test.py",),
        }
    )

    comparison = compare_issueplan_current_state(
        expected, current, current_scan_result=result
    )
    assert comparison.outcome == IssuePlanCurrentStateOutcome.STALE
    assert set(comparison.reason_codes) == {
        "contract.scope-changed",
        "contract.allowlist-changed",
        "contract.required-tests-changed",
    }


def test_unsupported_schema_version_fails_closed():
    expected, _ = _build()
    current, result = _build(schema_version="2.0")

    comparison = compare_issueplan_current_state(
        expected, current, current_scan_result=result
    )
    assert comparison.outcome == IssuePlanCurrentStateOutcome.BLOCKED
    assert "version.unsupported" in comparison.reason_codes


def test_field_states_distinguish_absent_null_omitted_and_unavailable():
    candidate = MetadataCandidate(
        1,
        "raw",
        {
            "entity_id": "issue-360",
            "revision": "candidate-1",
            "null_field": None,
        },
    )
    result = _scan_result(candidates=(candidate,))
    evidence, _ = _build(scan_result=result)
    states = {name: state for name, state, _ in evidence.governed_fields}

    assert states["absent_field"] == "absent"
    assert states["null_field"] == "null"
    assert states["omitted_field"] == "intentionally-omitted"
    assert states["unavailable_field"] == "unavailable"


def test_fingerprint_is_order_stable_for_mappings_and_sets():
    first = compute_issueplan_current_state_fingerprint(
        {"b": {"z", "a"}, "a": (2, 1)}
    )
    second = compute_issueplan_current_state_fingerprint(
        {"a": (2, 1), "b": {"a", "z"}}
    )
    assert first == second


def test_comparison_keeps_human_details_separate_from_reason_codes():
    expected, _ = _build()
    current = replace(expected, graph_reference="changed")

    comparison = compare_issueplan_current_state(expected, current)
    assert comparison.reason_codes == ("contract.scope-changed",)
    assert comparison.details == (
        "changed binding: graph.reference",
        "reason: contract.scope-changed",
    )


def test_scanner_result_fingerprint_change_is_stale():
    expected, _ = _build()
    current_result = replace(_scan_result(), evidence=("bounded=false",))
    current, _ = _build(scan_result=current_result)

    comparison = compare_issueplan_current_state(
        expected, current, current_scan_result=current_result
    )
    assert comparison.outcome == IssuePlanCurrentStateOutcome.STALE
    assert "candidate.changed" in comparison.reason_codes
    assert "scanner.result" in comparison.changed_bindings


def test_unknown_contract_binding_change_is_stale():
    expected, _ = _build()
    current, result = _build(
        contract={
            "scope": ("current-state evidence",),
            "allowlist": ("issueplan_current_state.py",),
            "required_tests": ("test_issueplan_current_state.py",),
            "future_binding": "changed",
        }
    )

    comparison = compare_issueplan_current_state(
        expected, current, current_scan_result=result
    )
    assert comparison.outcome == IssuePlanCurrentStateOutcome.STALE
    assert comparison.reason_codes == ("contract.scope-changed",)
    assert "contract.fingerprint" in comparison.changed_bindings


def test_freshness_boundary_change_is_stale():
    expected, _ = _build()
    current, result = _build(freshness_boundary="main@def456")

    comparison = compare_issueplan_current_state(
        expected, current, current_scan_result=result
    )
    assert comparison.outcome == IssuePlanCurrentStateOutcome.STALE
    assert "source.revision-changed" in comparison.reason_codes
    assert "freshness.boundary" in comparison.changed_bindings


def test_incomplete_expected_evidence_also_fails_closed():
    expected, _ = _build(retrieval_complete=False)
    current, result = _build()

    comparison = compare_issueplan_current_state(
        expected, current, current_scan_result=result
    )
    assert comparison.outcome == IssuePlanCurrentStateOutcome.BLOCKED
    assert "source.partial" in comparison.reason_codes
