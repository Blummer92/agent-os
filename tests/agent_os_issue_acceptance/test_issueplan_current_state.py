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


def _result(
    *,
    revision="rev-1",
    candidates=None,
    findings=(),
    adoption=AdoptionClass.STRICT_NATIVE,
):
    candidates = candidates or (
        MetadataCandidate(
            1,
            "raw",
            {
                "profile_version": "issueplan-core/v1",
                "entity_id": "issue-360",
                "revision": "candidate-1",
                "owner_agent": "Integration Manager",
                "required_files": ["b.py", "a.py"],
            },
        ),
    )
    return ScanResult(
        source_locator="github:Blummer92/agent-os#360",
        source_revision=revision,
        findings=findings,
        adoption_class=adoption,
        candidates=tuple(candidates),
        strict_valid=True,
        execution_authorized=False,
        evidence=("bounded=true",),
    )


def _build(
    *,
    revision="rev-1",
    result=None,
    observed_at="2026-07-20T01:00:00Z",
    **kwargs,
):
    result = result or _result(revision=revision)
    envelope = SourceEnvelope(
        source_locator="github:Blummer92/agent-os#360",
        source_revision=revision,
        content="issue body",
        retrieval_complete=kwargs.pop("retrieval_complete", True),
        pagination_complete=kwargs.pop("pagination_complete", True),
        accessible=kwargs.pop("accessible", True),
        source_family=kwargs.pop("source_family", "github-issue"),
        expected_revision=kwargs.pop("expected_revision", None),
    )
    return build_issueplan_current_state_evidence(
        envelope,
        result,
        observed_at=observed_at,
        freshness_boundary=kwargs.pop("freshness_boundary", "main@abc123"),
        governed_field_names=("absent_field", "null_field"),
        omitted_fields=("omitted_field",),
        repository=kwargs.pop("repository", "Blummer92/agent-os"),
        base_branch=kwargs.pop("base_branch", "main"),
        evaluated_repository_sha=kwargs.pop("evaluated_repository_sha", "a" * 40),
        implementation_contract_fingerprint=kwargs.pop(
            "implementation_contract_fingerprint", "b" * 64
        ),
        allowed_files=kwargs.pop("allowed_files", ("b.py", "a.py")),
        forbidden_paths=kwargs.pop("forbidden_paths", (".github/",)),
        required_tests=kwargs.pop("required_tests", ("pytest",)),
        graph_reference=kwargs.pop("graph_reference", "graph-digest"),
        planning_result_reference=kwargs.pop(
            "planning_result_reference", "planning-digest"
        ),
        handoff_reference=kwargs.pop("handoff_reference", "handoff-digest"),
        supplied_node_ids=kwargs.pop("supplied_node_ids", ("2", "1")),
        **kwargs,
    )


def test_outcome_values_are_exact():
    assert tuple(item.value for item in IssuePlanCurrentStateOutcome) == (
        "current",
        "stale",
        "blocked",
        "invalid",
        "needs-decision",
    )


def test_identical_evidence_is_current_and_never_authorized():
    first = _build()
    second = _build()
    result = compare_issueplan_current_state(first, second)
    assert first == second
    assert result.outcome == IssuePlanCurrentStateOutcome.CURRENT
    assert first.execution_authorized is result.execution_authorized is False


def test_observed_at_is_provenance_not_semantic_identity():
    first = _build(observed_at="2026-07-20T01:00:00Z")
    second = _build(observed_at="2026-07-20T02:00:00Z")
    assert first.evidence_id == second.evidence_id
    assert compute_issueplan_current_state_fingerprint(first) == (
        compute_issueplan_current_state_fingerprint(second)
    )
    assert compare_issueplan_current_state(first, second).outcome == (
        IssuePlanCurrentStateOutcome.CURRENT
    )


def test_models_are_frozen_and_authorization_is_not_constructible():
    evidence = _build()
    with pytest.raises(FrozenInstanceError):
        evidence.evidence_id = "changed"
    with pytest.raises(TypeError):
        IssuePlanCurrentStateEvidence(
            **{**evidence.__dict__, "execution_authorized": True}
        )


def test_set_like_fields_are_deterministic():
    first = _build(allowed_files=("a.py", "b.py"), supplied_node_ids=("1", "2"))
    second = _build(allowed_files=("b.py", "a.py"), supplied_node_ids=("2", "1"))
    assert first.evidence_id == second.evidence_id


def test_complete_candidate_order_is_binding():
    candidates = (
        MetadataCandidate(1, "one", {"entity_id": "issue-360"}),
        MetadataCandidate(2, "two", {"entity_id": "issue-360"}),
    )
    left = _build(result=_result(candidates=candidates))
    right = _build(result=_result(candidates=tuple(reversed(candidates))))
    comparison = compare_issueplan_current_state(left, right)
    assert comparison.outcome == IssuePlanCurrentStateOutcome.STALE
    assert "candidate.changed" in comparison.reason_codes


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"retrieval_complete": False}, "source.partial"),
        ({"pagination_complete": False}, "source.unknown-pagination"),
        ({"accessible": False}, "source.inaccessible"),
        ({"completeness_status": "truncated"}, "source.partial"),
        ({"retrieval_status": "absent"}, "projection.lookup-failed"),
        ({"retrieval_status": "unavailable"}, "projection.lookup-failed"),
    ],
)
def test_incomplete_or_unavailable_source_needs_decision(kwargs, reason):
    comparison = compare_issueplan_current_state(_build(), _build(**kwargs))
    assert comparison.outcome == IssuePlanCurrentStateOutcome.NEEDS_DECISION
    assert reason in comparison.reason_codes


def test_unsupported_source_is_blocked():
    comparison = compare_issueplan_current_state(
        _build(), _build(source_family="unsupported")
    )
    assert comparison.outcome == IssuePlanCurrentStateOutcome.BLOCKED
    assert "source.unsupported" in comparison.reason_codes


@pytest.mark.parametrize(
    ("finding", "adoption", "reason", "outcome"),
    [
        (
            ScanFinding.METADATA_DUPLICATED_IDENTICAL,
            AdoptionClass.ADOPTION_BLOCKED,
            "scanner.multiple-identical",
            IssuePlanCurrentStateOutcome.BLOCKED,
        ),
        (
            ScanFinding.METADATA_CONFLICTING,
            AdoptionClass.ADOPTION_BLOCKED,
            "scanner.multiple-conflicting",
            IssuePlanCurrentStateOutcome.BLOCKED,
        ),
        (
            ScanFinding.METADATA_MALFORMED,
            AdoptionClass.ADOPTION_BLOCKED,
            "scanner.malformed-candidate",
            IssuePlanCurrentStateOutcome.BLOCKED,
        ),
        (
            ScanFinding.UNKNOWN_GOVERNED_FIELD,
            AdoptionClass.ADOPTION_BLOCKED,
            "scanner.unknown-governed-field",
            IssuePlanCurrentStateOutcome.NEEDS_DECISION,
        ),
        (
            ScanFinding.IDENTITY_FINDING_PRESENT,
            AdoptionClass.IDENTITY_QUARANTINED,
            "identity.quarantined",
            IssuePlanCurrentStateOutcome.BLOCKED,
        ),
    ],
)
def test_scanner_findings_fail_closed(finding, adoption, reason, outcome):
    current = _build(result=_result(findings=(finding,), adoption=adoption))
    comparison = compare_issueplan_current_state(_build(), current)
    assert comparison.outcome == outcome
    assert reason in comparison.reason_codes


def test_field_states_distinguish_absent_null_omitted_and_unavailable():
    candidate = MetadataCandidate(
        1, "raw", {"entity_id": "issue-360", "null_field": None}
    )
    evidence = _build(
        result=_result(candidates=(candidate,)),
        field_state_overrides={"unavailable_field": "unavailable"},
    )
    states = {
        name: state for name, state, _ in evidence.source_snapshot.governed_fields
    }
    assert states["absent_field"] == "absent"
    assert states["null_field"] == "null"
    assert states["omitted_field"] == "intentionally-omitted"
    assert states["unavailable_field"] == "unavailable"


def test_revision_change_is_stale():
    expected = _build()
    current = _build(revision="rev-2", result=_result(revision="rev-2"))
    comparison = compare_issueplan_current_state(expected, current)
    assert comparison.outcome == IssuePlanCurrentStateOutcome.STALE
    assert {
        "candidate.changed",
        "source.revision-changed",
    } & set(comparison.reason_codes)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"allowed_files": ("other.py",)}, "contract.allowlist-changed"),
        ({"forbidden_paths": ("secrets/",)}, "contract.scope-changed"),
        ({"required_tests": ("other",)}, "contract.required-tests-changed"),
        ({"evaluated_repository_sha": "c" * 40}, "source.revision-changed"),
        ({"supplied_node_ids": ("3",)}, "contract.scope-changed"),
    ],
)
def test_governed_input_changes_are_stale(change, reason):
    comparison = compare_issueplan_current_state(_build(), _build(**change))
    assert comparison.outcome == IssuePlanCurrentStateOutcome.STALE
    assert reason in comparison.reason_codes


def test_unsupported_schema_is_invalid():
    current = _build(schema_version="2.0")
    comparison = compare_issueplan_current_state(_build(), current)
    assert comparison.outcome == IssuePlanCurrentStateOutcome.INVALID
    assert "version.unsupported" in comparison.reason_codes


def test_tampered_identity_is_invalid():
    evidence = _build()
    tampered = replace(
        evidence, evidence_id="issueplan-current-state:" + "0" * 64
    )
    comparison = compare_issueplan_current_state(tampered, tampered)
    assert comparison.outcome == IssuePlanCurrentStateOutcome.INVALID
    assert comparison.reason_codes == ("projection.incomplete",)


def test_source_and_scan_identity_must_match():
    with pytest.raises(ValueError):
        _build(revision="rev-2", result=_result(revision="rev-1"))


def test_status_override_cannot_weaken_source_evidence():
    with pytest.raises(ValueError, match="cannot weaken"):
        _build(retrieval_complete=False, completeness_status="complete")


def test_no_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("external operation attempted")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)
    result = compare_issueplan_current_state(_build(), _build())
    assert result.outcome == IssuePlanCurrentStateOutcome.CURRENT
