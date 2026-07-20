from dataclasses import FrozenInstanceError, replace

import pytest

from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION,
    IssuePlanCurrentStateEvidence,
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


def _contract(**extra):
    return {
        "scope": ("current-state evidence",),
        "allowlist": ("issueplan_current_state.py",),
        "required_tests": ("test_issueplan_current_state.py",),
        **extra,
    }


def _scan_result(
    *,
    source_locator: str = "github:Blummer92/agent-os#360",
    source_revision: str = "rev-1",
    findings: tuple[ScanFinding, ...] = (),
    candidates: tuple[MetadataCandidate, ...] | None = None,
    execution_authorized: bool = False,
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
        source_locator=source_locator,
        source_revision=source_revision,
        findings=findings,
        adoption_class=AdoptionClass.STRICT_NATIVE,
        candidates=candidates,
        strict_valid=True,
        execution_authorized=execution_authorized,
        evidence=("bounded=true",),
    )


def _build(
    *,
    source_locator: str = "github:Blummer92/agent-os#360",
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
    expected_revision: str | None = None,
    graph_reference: str | None = "graph-digest",
    planning_result_reference: str | None = "planning-digest",
    handoff_reference: str | None = "handoff-digest",
):
    result = scan_result or _scan_result(
        source_locator=source_locator,
        source_revision=source_revision,
    )
    envelope = SourceEnvelope(
        source_locator=source_locator,
        source_revision=source_revision,
        content=content,
        retrieval_complete=retrieval_complete,
        pagination_complete=pagination_complete,
        accessible=accessible,
        source_family=source_family,
        expected_revision=expected_revision,
    )
    evidence = build_issueplan_current_state_evidence(
        envelope=envelope,
        scan_result=result,
        observed_at="2026-07-20T01:00:00Z",
        freshness_boundary=freshness_boundary,
        implementation_contract=contract or _contract(),
        governed_field_names=("absent_field", "null_field"),
        intentionally_omitted_fields=("omitted_field",),
        unavailable_fields=("unavailable_field",),
        graph_reference=graph_reference,
        planning_result_reference=planning_result_reference,
        handoff_reference=handoff_reference,
        projection_complete=projection_complete,
        projection_lookup_succeeded=projection_lookup_succeeded,
        schema_version=schema_version,
    )
    return evidence, result


def _rehash(evidence):
    payload = {
        field: value
        for field, value in evidence.__dict__.items()
        if field != "evidence_id"
    }
    payload["execution_authorized"] = False
    return replace(
        evidence,
        evidence_id=compute_issueplan_current_state_fingerprint(payload),
    )


def test_public_outcome_values_are_exact():
    assert tuple(item.value for item in IssuePlanCurrentStateOutcome) == (
        "current",
        "stale",
        "blocked",
        "invalid",
        "needs-decision",
    )


def test_identical_inputs_are_current_deterministic_and_never_authorized():
    first, scan_result = _build()
    second, _ = _build()
    assert first == second
    comparison = compare_issueplan_current_state(
        first, second, current_scan_result=scan_result
    )
    assert comparison.outcome is IssuePlanCurrentStateOutcome.CURRENT
    assert comparison.reason_codes == ()
    assert comparison.changed_bindings == ()
    assert comparison.execution_authorized is False


def test_models_are_frozen_and_authorization_is_not_constructible():
    evidence, _ = _build()
    with pytest.raises(FrozenInstanceError):
        evidence.evidence_id = "changed"
    with pytest.raises(TypeError):
        IssuePlanCurrentStateEvidence(
            **{**evidence.__dict__, "execution_authorized": True}
        )


@pytest.mark.parametrize("missing", ["scope", "allowlist", "required_tests"])
def test_builder_rejects_missing_required_contract_fields(missing):
    contract = _contract()
    contract.pop(missing)
    with pytest.raises(ValueError, match="missing required fields"):
        _build(contract=contract)


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", "not-a-collection"),
        ("allowlist", {}),
        ("required_tests", ()),
        ("scope", ("",)),
        ("allowlist", (" spaced ",)),
    ],
)
def test_builder_rejects_unsupported_contract_collection_shapes(field, value):
    contract = _contract()
    contract[field] = value
    with pytest.raises((TypeError, ValueError)):
        _build(contract=contract)


def test_builder_rejects_source_locator_mismatch():
    result = _scan_result(source_locator="github:other/repo#1")
    with pytest.raises(ValueError, match="bind to the supplied source envelope"):
        _build(scan_result=result)


def test_builder_rejects_source_revision_mismatch():
    result = _scan_result(source_revision="rev-2")
    with pytest.raises(ValueError, match="bind to the supplied source envelope"):
        _build(scan_result=result)


def test_builder_rejects_authorizing_scan_result():
    result = _scan_result(execution_authorized=True)
    with pytest.raises(ValueError, match="cannot authorize execution"):
        _build(scan_result=result)


def test_builder_rejects_overlapping_omitted_and_unavailable_fields():
    envelope = SourceEnvelope(
        source_locator="github:Blummer92/agent-os#360",
        source_revision="rev-1",
        content="body",
    )
    with pytest.raises(ValueError, match="must be disjoint"):
        build_issueplan_current_state_evidence(
            envelope=envelope,
            scan_result=_scan_result(),
            observed_at="2026-07-20T01:00:00Z",
            freshness_boundary="main@abc123",
            implementation_contract=_contract(),
            intentionally_omitted_fields=("field",),
            unavailable_fields=("field",),
        )


@pytest.mark.parametrize(
    "field_names",
    [
        ("",),
        (" spaced ",),
        ("bad/name",),
        ("x" * 129,),
    ],
)
def test_builder_rejects_unbounded_governed_field_names(field_names):
    envelope = SourceEnvelope(
        source_locator="github:Blummer92/agent-os#360",
        source_revision="rev-1",
        content="body",
    )
    with pytest.raises((TypeError, ValueError)):
        build_issueplan_current_state_evidence(
            envelope=envelope,
            scan_result=_scan_result(),
            observed_at="2026-07-20T01:00:00Z",
            freshness_boundary="main@abc123",
            implementation_contract=_contract(),
            governed_field_names=field_names,
        )


def test_builder_rejects_unsupported_schema_version():
    with pytest.raises(ValueError, match="unsupported"):
        _build(schema_version="2.0")


def test_compare_classifies_supported_tampered_schema_as_invalid():
    evidence, _ = _build()
    tampered = replace(evidence, schema_version="2.0")
    tampered = _rehash(tampered)
    comparison = compare_issueplan_current_state(evidence, tampered)
    assert comparison.outcome is IssuePlanCurrentStateOutcome.INVALID
    assert "version.unsupported" in comparison.reason_codes


def test_tampered_evidence_id_is_invalid():
    evidence, _ = _build()
    tampered = replace(evidence, evidence_id="0" * 64)
    comparison = compare_issueplan_current_state(tampered, tampered)
    assert comparison.outcome is IssuePlanCurrentStateOutcome.INVALID
    assert comparison.reason_codes == ("projection.incomplete",)


@pytest.mark.parametrize(
    "finding,reason",
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
def test_ambiguous_scanner_findings_need_decision(finding, reason):
    result = _scan_result(findings=(finding,))
    evidence, _ = _build(scan_result=result)
    comparison = compare_issueplan_current_state(evidence, evidence)
    assert comparison.outcome is IssuePlanCurrentStateOutcome.NEEDS_DECISION
    assert reason in comparison.reason_codes


@pytest.mark.parametrize(
    "kwargs,reason",
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
def test_incomplete_or_unavailable_evidence_is_blocked(kwargs, reason):
    evidence, _ = _build(**kwargs)
    comparison = compare_issueplan_current_state(evidence, evidence)
    assert comparison.outcome is IssuePlanCurrentStateOutcome.BLOCKED
    assert reason in comparison.reason_codes


def test_source_revision_change_is_stale():
    expected, _ = _build()
    current, result = _build(
        source_revision="rev-2",
        scan_result=_scan_result(source_revision="rev-2"),
    )
    comparison = compare_issueplan_current_state(
        expected, current, current_scan_result=result
    )
    assert comparison.outcome is IssuePlanCurrentStateOutcome.STALE
    assert "source.revision-changed" in comparison.reason_codes


def test_freshness_boundary_has_dedicated_reason():
    expected, _ = _build()
    current, _ = _build(freshness_boundary="main@def456")
    comparison = compare_issueplan_current_state(expected, current)
    assert comparison.outcome is IssuePlanCurrentStateOutcome.STALE
    assert comparison.reason_codes == ("source.freshness-boundary-changed",)
    assert comparison.changed_bindings == ("freshness.boundary",)


def test_contract_changes_have_specific_reasons():
    expected, _ = _build()
    current, _ = _build(
        contract={
            "scope": ("changed",),
            "allowlist": ("other.py",),
            "required_tests": ("other_test.py",),
        }
    )
    comparison = compare_issueplan_current_state(expected, current)
    assert comparison.outcome is IssuePlanCurrentStateOutcome.STALE
    assert set(comparison.reason_codes) == {
        "contract.scope-changed",
        "contract.allowlist-changed",
        "contract.required-tests-changed",
    }


def test_unknown_contract_binding_is_scope_change():
    expected, _ = _build()
    current, _ = _build(contract=_contract(future_binding="changed"))
    comparison = compare_issueplan_current_state(expected, current)
    assert comparison.outcome is IssuePlanCurrentStateOutcome.STALE
    assert comparison.reason_codes == ("contract.scope-changed",)
    assert "contract.fingerprint" in comparison.changed_bindings


@pytest.mark.parametrize(
    "field,value,binding",
    [
        ("graph_reference", "changed", "graph.reference"),
        ("planning_result_reference", "changed", "planning-result.reference"),
        ("handoff_reference", "changed", "handoff.reference"),
    ],
)
def test_planning_references_expose_drift_without_issueplan_reason(field, value, binding):
    expected, _ = _build()
    current, _ = _build(**{field: value})
    comparison = compare_issueplan_current_state(expected, current)
    assert comparison.outcome is IssuePlanCurrentStateOutcome.STALE
    assert comparison.reason_codes == ()
    assert comparison.changed_bindings == (binding,)


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


def test_reason_codes_and_bindings_are_sorted_and_deduplicated():
    expected, _ = _build()
    current, _ = _build(
        source_revision="rev-2",
        scan_result=_scan_result(
            source_revision="rev-2",
            findings=(
                ScanFinding.METADATA_CONFLICTING,
                ScanFinding.METADATA_CONFLICTING,
            ),
        ),
    )
    comparison = compare_issueplan_current_state(expected, current)
    assert comparison.reason_codes == tuple(sorted(set(comparison.reason_codes)))
    assert comparison.changed_bindings == tuple(
        sorted(set(comparison.changed_bindings))
    )


def test_supplied_scan_result_mismatch_is_invalid():
    evidence, _ = _build()
    mismatched = replace(_scan_result(), evidence=("different",))
    comparison = compare_issueplan_current_state(
        evidence, evidence, current_scan_result=mismatched
    )
    assert comparison.outcome is IssuePlanCurrentStateOutcome.INVALID
    assert "projection.incomplete" in comparison.reason_codes


def test_build_and_compare_do_not_require_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("external operation attempted")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)
    first, scan_result = _build()
    second, _ = _build()
    comparison = compare_issueplan_current_state(
        first, second, current_scan_result=scan_result
    )
    assert comparison.outcome is IssuePlanCurrentStateOutcome.CURRENT
