import json
from dataclasses import FrozenInstanceError, replace

import pytest

from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION,
    IssuePlanCurrentStateComparison,
    IssuePlanCurrentStateEvidence,
    IssuePlanCurrentStateOutcome,
    build_issueplan_current_state_evidence,
    compare_issueplan_current_state,
    compute_issueplan_current_state_fingerprint,
    reconstruct_issueplan_current_state_comparison,
    serialize_issueplan_current_state_comparison,
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


def test_freshness_boundary_has_dedicated_reason():
    comparison = compare_issueplan_current_state(
        _build(), _build(freshness_boundary="main@def456")
    )
    assert comparison.outcome == IssuePlanCurrentStateOutcome.STALE
    assert comparison.changed_bindings == ("freshness_boundary",)
    assert comparison.reason_codes == ("source.freshness-boundary-changed",)


@pytest.mark.parametrize(
    "change",
    [
        {"graph_reference": "changed-graph"},
        {"planning_result_reference": "changed-planning"},
        {"handoff_reference": "changed-handoff"},
    ],
)
def test_planning_reference_changes_are_neutral_issueplan_bindings(change):
    comparison = compare_issueplan_current_state(_build(), _build(**change))
    assert comparison.outcome == IssuePlanCurrentStateOutcome.STALE
    assert comparison.changed_bindings == (next(iter(change)),)
    assert comparison.reason_codes == ()


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


def _compare(outcome):
    """Build one real comparison per supported outcome from canonical evidence."""
    current = {
        IssuePlanCurrentStateOutcome.CURRENT: {},
        IssuePlanCurrentStateOutcome.STALE: {"freshness_boundary": "main@def456"},
        IssuePlanCurrentStateOutcome.BLOCKED: {"source_family": "unsupported"},
        IssuePlanCurrentStateOutcome.INVALID: {"schema_version": "2.0"},
        IssuePlanCurrentStateOutcome.NEEDS_DECISION: {"retrieval_complete": False},
    }[outcome]
    comparison = compare_issueplan_current_state(_build(), _build(**current))
    assert comparison.outcome == outcome
    return comparison


def _raw_comparison(**overrides):
    values = {
        "expected_evidence_id": "issueplan-current-state:" + "a" * 64,
        "current_evidence_id": "issueplan-current-state:" + "b" * 64,
        "expected_fingerprint": "a" * 64,
        "current_fingerprint": "b" * 64,
        "changed_bindings": ("allowed_files",),
        "outcome": IssuePlanCurrentStateOutcome.STALE,
        "reason_codes": ("contract.allowlist-changed",),
        "details": ("changed:allowed_files",),
    }
    values.update(overrides)
    return IssuePlanCurrentStateComparison(**values)


def _payload(comparison=None):
    return json.loads(
        serialize_issueplan_current_state_comparison(comparison or _raw_comparison())
    )


@pytest.mark.parametrize("outcome", list(IssuePlanCurrentStateOutcome))
def test_comparison_transport_round_trips_every_outcome(outcome):
    comparison = _compare(outcome)
    restored = reconstruct_issueplan_current_state_comparison(
        serialize_issueplan_current_state_comparison(comparison)
    )
    assert type(restored) is IssuePlanCurrentStateComparison
    assert restored == comparison
    assert restored.outcome is outcome
    assert restored.execution_authorized is False


def test_comparison_transport_is_deterministic():
    first = serialize_issueplan_current_state_comparison(_compare(
        IssuePlanCurrentStateOutcome.STALE
    ))
    second = serialize_issueplan_current_state_comparison(_compare(
        IssuePlanCurrentStateOutcome.STALE
    ))
    assert first == second
    assert first == serialize_issueplan_current_state_comparison(
        reconstruct_issueplan_current_state_comparison(first)
    )


@pytest.mark.parametrize("outcome", list(IssuePlanCurrentStateOutcome))
def test_serializer_output_is_reconstructible_and_byte_stable(outcome):
    payload = serialize_issueplan_current_state_comparison(_compare(outcome))
    restored = reconstruct_issueplan_current_state_comparison(payload)
    assert serialize_issueplan_current_state_comparison(restored) == payload
    assert reconstruct_issueplan_current_state_comparison(
        payload.decode("utf-8")
    ) == restored


@pytest.mark.parametrize("outcome", list(IssuePlanCurrentStateOutcome))
def test_outcome_uses_its_exact_enum_value(outcome):
    comparison = _compare(outcome)
    assert _payload(comparison)["outcome"] == outcome.value


def test_transport_preserves_bindings_reasons_details_and_identities():
    comparison = _compare(IssuePlanCurrentStateOutcome.STALE)
    payload = _payload(comparison)
    assert comparison.changed_bindings == ("freshness_boundary",)
    assert comparison.reason_codes == ("source.freshness-boundary-changed",)
    assert comparison.details == ("changed:freshness_boundary",)
    assert payload["changed_bindings"] == list(comparison.changed_bindings)
    assert payload["reason_codes"] == list(comparison.reason_codes)
    assert payload["details"] == list(comparison.details)
    assert payload["expected_evidence_id"] == comparison.expected_evidence_id
    assert payload["current_evidence_id"] == comparison.current_evidence_id
    assert payload["expected_fingerprint"] == comparison.expected_fingerprint
    assert payload["current_fingerprint"] == comparison.current_fingerprint
    assert payload["execution_authorized"] is False


def test_multiple_bindings_reasons_and_details_survive_transport():
    comparison = _raw_comparison(
        changed_bindings=("allowed_files", "required_tests"),
        reason_codes=(
            "contract.allowlist-changed",
            "contract.required-tests-changed",
        ),
        details=("changed:allowed_files", "changed:required_tests"),
    )
    restored = reconstruct_issueplan_current_state_comparison(
        serialize_issueplan_current_state_comparison(comparison)
    )
    assert restored == comparison
    assert restored.changed_bindings == ("allowed_files", "required_tests")
    assert restored.reason_codes == (
        "contract.allowlist-changed",
        "contract.required-tests-changed",
    )
    assert restored.details == ("changed:allowed_files", "changed:required_tests")


_TRANSPORT_FIELDS = (
    "changed_bindings",
    "current_evidence_id",
    "current_fingerprint",
    "details",
    "execution_authorized",
    "expected_evidence_id",
    "expected_fingerprint",
    "outcome",
    "reason_codes",
)


def test_transport_carries_exactly_the_declared_fields():
    assert sorted(_payload()) == list(_TRANSPORT_FIELDS)


@pytest.mark.parametrize("missing", _TRANSPORT_FIELDS)
def test_missing_transport_field_is_rejected(missing):
    payload = _payload()
    payload.pop(missing)
    with pytest.raises(ValueError, match="missing required fields"):
        reconstruct_issueplan_current_state_comparison(payload)


def test_unknown_transport_field_is_rejected():
    with pytest.raises(ValueError, match="unknown fields"):
        reconstruct_issueplan_current_state_comparison({**_payload(), "extra": "x"})


@pytest.mark.parametrize(
    "outcome",
    ["current-state", "CURRENT", "", None, 1, True, ["stale"]],
)
def test_malformed_outcome_is_rejected(outcome):
    with pytest.raises(ValueError):
        reconstruct_issueplan_current_state_comparison(
            {**_payload(), "outcome": outcome}
        )


@pytest.mark.parametrize("name", ["changed_bindings", "reason_codes", "details"])
@pytest.mark.parametrize(
    "value",
    ["allowed_files", ("allowed_files",), [1], [None], [""], [["allowed_files"]], None],
)
def test_malformed_sequence_transport_is_rejected(name, value):
    with pytest.raises(ValueError):
        reconstruct_issueplan_current_state_comparison({**_payload(), name: value})


@pytest.mark.parametrize(
    "name",
    [
        "expected_evidence_id",
        "current_evidence_id",
        "expected_fingerprint",
        "current_fingerprint",
    ],
)
@pytest.mark.parametrize("bad", ["", "   ", None, 1, True, ["a"]])
def test_identity_and_fingerprint_drift_is_rejected(name, bad):
    with pytest.raises(ValueError, match="non-empty string"):
        reconstruct_issueplan_current_state_comparison({**_payload(), name: bad})


@pytest.mark.parametrize("value", [True, 1, "false", None, 0])
def test_execution_authorized_must_remain_false(value):
    with pytest.raises(ValueError, match="execution_authorized"):
        reconstruct_issueplan_current_state_comparison(
            {**_payload(), "execution_authorized": value}
        )


@pytest.mark.parametrize(
    "drift",
    [
        {"changed_bindings": ["required_tests", "allowed_files"]},
        {"changed_bindings": ["allowed_files", "allowed_files"]},
        {
            "reason_codes": [
                "contract.required-tests-changed",
                "contract.allowlist-changed",
            ]
        },
        {"reason_codes": ["contract.allowlist-changed", "contract.allowlist-changed"]},
    ],
)
def test_noncanonical_payload_drift_is_rejected_not_repaired(drift):
    base = _payload(
        _raw_comparison(
            changed_bindings=("allowed_files", "required_tests"),
            reason_codes=(
                "contract.allowlist-changed",
                "contract.required-tests-changed",
            ),
        )
    )
    with pytest.raises(ValueError, match="not canonical"):
        reconstruct_issueplan_current_state_comparison({**base, **drift})


def test_unsupported_reason_vocabulary_is_rejected():
    with pytest.raises(ValueError, match="bounded IssuePlanCore vocabulary"):
        reconstruct_issueplan_current_state_comparison(
            {**_payload(), "reason_codes": ["contract.unknown-change"]}
        )


@pytest.mark.parametrize(
    "text",
    [
        '{"outcome": "stale"}',
        "not json",
        '["stale"]',
        '{"expected_evidence_id": "a", }',
    ],
)
def test_malformed_transport_text_is_rejected(text):
    with pytest.raises(ValueError):
        reconstruct_issueplan_current_state_comparison(text)


def test_noncanonical_encoding_is_rejected():
    payload = _payload()
    with pytest.raises(ValueError, match="canonical"):
        reconstruct_issueplan_current_state_comparison(
            json.dumps(payload, indent=2).encode("utf-8")
        )
    with pytest.raises(ValueError, match="canonical"):
        reconstruct_issueplan_current_state_comparison(
            json.dumps(payload, sort_keys=True, separators=(", ", ": "))
        )
    with pytest.raises(ValueError, match="canonical"):
        reconstruct_issueplan_current_state_comparison(
            json.dumps(dict(reversed(list(payload.items()))), separators=(",", ":"))
        )


@pytest.mark.parametrize("payload", [1, 1.5, None, b"\xff\xfe", object()])
def test_unsupported_transport_container_is_rejected(payload):
    with pytest.raises((TypeError, ValueError)):
        reconstruct_issueplan_current_state_comparison(payload)


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_evidence_id": ""},
        {"current_evidence_id": "   "},
        {"expected_fingerprint": 1},
        {"current_fingerprint": None},
        {"details": ("",)},
    ],
)
def test_serializer_fails_closed_on_non_round_trippable_comparison(overrides):
    comparison = _raw_comparison(**overrides)
    with pytest.raises(ValueError, match="invalid current-state fields"):
        serialize_issueplan_current_state_comparison(comparison)


def test_constructor_owned_detail_coercion_is_transported_not_re_coerced():
    comparison = _raw_comparison(details=(1, 2))
    assert comparison.details == ("1", "2")
    assert _payload(comparison)["details"] == ["1", "2"]
    assert reconstruct_issueplan_current_state_comparison(
        serialize_issueplan_current_state_comparison(comparison)
    ) == comparison


def test_serializer_requires_the_exact_comparison_type():
    class Subclass(IssuePlanCurrentStateComparison):
        pass

    with pytest.raises(TypeError):
        serialize_issueplan_current_state_comparison(
            Subclass(**{
                "expected_evidence_id": "a",
                "current_evidence_id": "b",
                "expected_fingerprint": "c",
                "current_fingerprint": "d",
                "changed_bindings": (),
                "outcome": IssuePlanCurrentStateOutcome.CURRENT,
                "reason_codes": (),
            })
        )
    with pytest.raises(TypeError):
        serialize_issueplan_current_state_comparison(_payload())


def test_transport_does_not_mutate_its_input():
    comparison = _compare(IssuePlanCurrentStateOutcome.STALE)
    reference = compare_issueplan_current_state(
        _build(), _build(freshness_boundary="main@def456")
    )
    payload = _payload(comparison)
    snapshot = json.loads(json.dumps(payload))
    restored = reconstruct_issueplan_current_state_comparison(payload)
    assert payload == snapshot
    assert comparison == reference
    assert restored == reference


def test_comparison_semantics_are_unchanged_by_transport():
    for outcome in IssuePlanCurrentStateOutcome:
        comparison = _compare(outcome)
        restored = reconstruct_issueplan_current_state_comparison(
            serialize_issueplan_current_state_comparison(comparison)
        )
        assert _compare(outcome) == comparison == restored


def test_transport_performs_no_external_io(monkeypatch):
    comparison = _compare(IssuePlanCurrentStateOutcome.NEEDS_DECISION)
    payload = serialize_issueplan_current_state_comparison(comparison)

    def forbidden(*args, **kwargs):
        raise AssertionError("external operation attempted")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    assert serialize_issueplan_current_state_comparison(comparison) == payload
    assert reconstruct_issueplan_current_state_comparison(payload) == comparison
