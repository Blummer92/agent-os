"""AOS-AUTO1C repository-observation stage tests (#752)."""

from __future__ import annotations

import ast
import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.agent_os_candidate_packet import repository_stage
from scripts.agent_os_candidate_packet.repository_stage import (
    REPOSITORY_OBSERVATION_REJECTED,
    RepositoryObservation,
    RepositoryStageResult,
    RepositoryStageStatus,
    prepare_repository_state_evidence,
    repository_state_evidence_from_dict,
    repository_state_evidence_to_dict,
)
from scripts.agent_os_execution_capabilities import (
    RepositoryEvidenceType,
    RepositoryIdentity,
    WorktreeState,
)

_HEAD_SHA = "a" * 40
_BASE_SHA = "b" * 40
_MERGE_SHA = "c" * 40
_PUSHED_SHA = "d" * 40
_BUILD_SHA = "e" * 40
_CONTRACT = "3" * 64
_OTHER_CONTRACT = "4" * 64


def _identity(**overrides) -> RepositoryIdentity:
    values = dict(host="github.com", owner="blummer92", repository="agent-os")
    values.update(overrides)
    return RepositoryIdentity(**values)


def _observation(**overrides) -> RepositoryObservation:
    """One clean branch-head observation. Every fact is stated explicitly."""
    values = dict(
        producer_adapter="fixture-read-only-adapter",
        producer_adapter_version="1.0",
        correlation_id="issue-752",
        repository_identity=_identity(),
        base_ref="main",
        base_sha=_BASE_SHA,
        head_ref="agent/752-repository-proposal-coordinator",
        head_sha=_HEAD_SHA,
        requested_ref="agent/752-repository-proposal-coordinator",
        requested_sha=_HEAD_SHA,
        observed_sha=_HEAD_SHA,
        tested_sha=_HEAD_SHA,
        pushed_sha=None,
        proposed_pr_sha=None,
        synthetic_merge_sha=None,
        external_build_sha=None,
        evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        contract_fingerprint=_CONTRACT,
        worktree_state=WorktreeState.CLEAN,
        observed_at="2026-08-06T04:00:00Z",
        freshness_boundary="main@41ebab11",
    )
    values.update(overrides)
    return RepositoryObservation(**values)


# --------------------------------------------------------------------------
# Evidence-type distinctions.
# --------------------------------------------------------------------------


def test_branch_head_observation_produces_valid_canonical_evidence() -> None:
    result = prepare_repository_state_evidence(_observation())

    assert result.status is RepositoryStageStatus.VALID
    assert result.reason_codes == ()
    assert result.evidence is not None
    assert result.evidence.evidence_type is RepositoryEvidenceType.BRANCH_HEAD
    assert result.evidence.evidence_id
    assert result.validation is not None
    assert result.validation.outcome == "valid"


def test_base_sha_evidence_binds_the_base_without_losing_the_head() -> None:
    result = prepare_repository_state_evidence(
        _observation(
            evidence_type=RepositoryEvidenceType.BASE_SHA,
            observed_sha=_BASE_SHA,
            tested_sha=_BASE_SHA,
        )
    )

    assert result.status is RepositoryStageStatus.VALID
    assert result.evidence.observed_sha == _BASE_SHA
    assert result.evidence.tested_sha == _BASE_SHA
    # The branch head is still recorded, and is still a distinct identity.
    assert result.evidence.head_sha == _HEAD_SHA
    assert result.evidence.tested_sha != result.evidence.head_sha


def test_synthetic_merge_keeps_source_and_tested_identities_distinct() -> None:
    result = prepare_repository_state_evidence(
        _observation(
            evidence_type=RepositoryEvidenceType.SYNTHETIC_PR_MERGE,
            observed_sha=_MERGE_SHA,
            tested_sha=_MERGE_SHA,
            synthetic_merge_sha=_MERGE_SHA,
        )
    )

    assert result.status is RepositoryStageStatus.VALID
    assert result.evidence.synthetic_merge_sha == _MERGE_SHA
    assert result.evidence.requested_sha == _HEAD_SHA
    assert result.evidence.tested_sha != result.evidence.requested_sha


def test_branch_head_evidence_rejects_a_synthetic_merge_sha() -> None:
    result = prepare_repository_state_evidence(
        _observation(synthetic_merge_sha=_MERGE_SHA)
    )

    assert result.status is RepositoryStageStatus.STALE
    assert "ref.test-sha-mismatch" in result.reason_codes


def test_synthetic_merge_evidence_requires_its_merge_sha() -> None:
    result = prepare_repository_state_evidence(
        _observation(
            evidence_type=RepositoryEvidenceType.SYNTHETIC_PR_MERGE,
            synthetic_merge_sha=None,
        )
    )

    assert result.status is RepositoryStageStatus.STALE
    assert "ref.test-sha-mismatch" in result.reason_codes


def test_uncommitted_worktree_evidence_is_blocked() -> None:
    result = prepare_repository_state_evidence(
        _observation(evidence_type=RepositoryEvidenceType.UNCOMMITTED_WORKTREE)
    )

    assert result.status is RepositoryStageStatus.BLOCKED
    assert "worktree.uncommitted" in result.reason_codes


# --------------------------------------------------------------------------
# SHA-role separation: source, candidate, tested, evaluator, build.
# --------------------------------------------------------------------------


def test_missing_tested_sha_is_never_inferred_from_the_head() -> None:
    result = prepare_repository_state_evidence(_observation(tested_sha=None))

    assert result.status is RepositoryStageStatus.STALE
    assert "ref.test-sha-mismatch" in result.reason_codes
    assert result.evidence.tested_sha is None


def test_requested_sha_drifting_from_the_head_is_reported() -> None:
    result = prepare_repository_state_evidence(_observation(requested_sha=_MERGE_SHA))

    assert result.status is RepositoryStageStatus.STALE
    assert "ref.test-sha-mismatch" in result.reason_codes


def test_external_build_sha_must_match_what_was_tested() -> None:
    result = prepare_repository_state_evidence(
        _observation(external_build_sha=_BUILD_SHA)
    )

    assert result.status is RepositoryStageStatus.STALE
    assert "ref.build-sha-mismatch" in result.reason_codes

    matched = prepare_repository_state_evidence(
        _observation(external_build_sha=_HEAD_SHA)
    )
    assert matched.status is RepositoryStageStatus.VALID


def test_pushed_and_pr_shas_stay_separate_identities() -> None:
    pushed = prepare_repository_state_evidence(_observation(pushed_sha=_PUSHED_SHA))
    assert pushed.status is RepositoryStageStatus.STALE
    assert "ref.stale-sha" in pushed.reason_codes

    proposed = prepare_repository_state_evidence(
        _observation(proposed_pr_sha=_PUSHED_SHA)
    )
    assert proposed.status is RepositoryStageStatus.STALE
    assert "ref.pr-head-mismatch" in proposed.reason_codes


def test_every_sha_role_is_preserved_independently() -> None:
    result = prepare_repository_state_evidence(
        _observation(
            pushed_sha=_HEAD_SHA,
            proposed_pr_sha=_HEAD_SHA,
            external_build_sha=_HEAD_SHA,
        )
    )

    assert result.status is RepositoryStageStatus.VALID
    evidence = result.evidence
    assert evidence.base_sha == _BASE_SHA
    assert evidence.head_sha == _HEAD_SHA
    assert evidence.requested_sha == _HEAD_SHA
    assert evidence.observed_sha == _HEAD_SHA
    assert evidence.tested_sha == _HEAD_SHA
    assert evidence.pushed_sha == _HEAD_SHA
    assert evidence.proposed_pr_sha == _HEAD_SHA
    assert evidence.external_build_sha == _HEAD_SHA
    assert evidence.synthetic_merge_sha is None


# --------------------------------------------------------------------------
# Worktree evidence.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("worktree_state", "expected_status", "expected_reason"),
    [
        (WorktreeState.CLEAN, RepositoryStageStatus.VALID, None),
        (WorktreeState.DIRTY, RepositoryStageStatus.BLOCKED, "worktree.dirty"),
        (
            WorktreeState.INDETERMINATE,
            RepositoryStageStatus.NEEDS_DECISION,
            "worktree.indeterminate",
        ),
    ],
)
def test_clean_dirty_and_indeterminate_worktrees_stay_distinct(
    worktree_state, expected_status, expected_reason
) -> None:
    result = prepare_repository_state_evidence(
        _observation(worktree_state=worktree_state)
    )

    assert result.status is expected_status
    assert result.evidence.worktree_state is worktree_state
    if expected_reason is None:
        assert result.reason_codes == ()
    else:
        assert expected_reason in result.reason_codes


def test_supplied_worktree_reason_codes_are_carried_through() -> None:
    result = prepare_repository_state_evidence(
        _observation(
            worktree_state=WorktreeState.DIRTY,
            worktree_reason_codes=("worktree.untracked", "worktree.dirty"),
        )
    )

    assert result.status is RepositoryStageStatus.BLOCKED
    assert "worktree.untracked" in result.reason_codes
    assert result.evidence.worktree_reason_codes == (
        "worktree.dirty",
        "worktree.untracked",
    )


def test_unapproved_worktree_reason_code_fails_closed() -> None:
    result = prepare_repository_state_evidence(
        _observation(worktree_reason_codes=("worktree.invented",))
    )

    assert result.status is RepositoryStageStatus.INVALID
    assert result.reason_codes == (REPOSITORY_OBSERVATION_REJECTED,)
    assert result.evidence is None
    assert result.validation is None


# --------------------------------------------------------------------------
# Expected bindings: identity and implementation contract.
# --------------------------------------------------------------------------


def test_repository_identity_mismatch_is_reported() -> None:
    result = prepare_repository_state_evidence(
        _observation(),
        expected_repository=_identity(owner="someone-else"),
    )

    assert result.status is RepositoryStageStatus.STALE
    assert "repo.identity-mismatch" in result.reason_codes


def test_fork_upstream_mismatch_is_distinct_from_identity_mismatch() -> None:
    result = prepare_repository_state_evidence(
        _observation(),
        expected_repository=_identity(default_branch="develop"),
    )

    assert result.status is RepositoryStageStatus.STALE
    assert "repo.fork-upstream-mismatch" in result.reason_codes


def test_contract_fingerprint_mismatch_is_reported() -> None:
    result = prepare_repository_state_evidence(
        _observation(),
        expected_contract_fingerprint=_OTHER_CONTRACT,
    )

    assert result.status is RepositoryStageStatus.STALE
    assert "ref.contract-mismatch" in result.reason_codes


def test_matching_expectations_stay_valid() -> None:
    result = prepare_repository_state_evidence(
        _observation(),
        expected_repository=_identity(),
        expected_base_ref="main",
        expected_base_sha=_BASE_SHA,
        expected_head_ref="agent/752-repository-proposal-coordinator",
        expected_head_sha=_HEAD_SHA,
        expected_requested_sha=_HEAD_SHA,
        expected_contract_fingerprint=_CONTRACT,
    )

    assert result.status is RepositoryStageStatus.VALID
    assert result.reason_codes == ()


def test_base_and_head_ref_mismatches_are_reported() -> None:
    base = prepare_repository_state_evidence(
        _observation(), expected_base_ref="release"
    )
    assert "ref.base-mismatch" in base.reason_codes

    head = prepare_repository_state_evidence(
        _observation(), expected_head_ref="other-branch"
    )
    assert "ref.head-mismatch" in head.reason_codes

    moved = prepare_repository_state_evidence(
        _observation(), expected_head_sha=_MERGE_SHA
    )
    assert "ref.branch-moved" in moved.reason_codes


# --------------------------------------------------------------------------
# Deterministic identity and round trip.
# --------------------------------------------------------------------------


def test_evidence_identity_is_deterministic() -> None:
    first = prepare_repository_state_evidence(_observation())
    second = prepare_repository_state_evidence(_observation())

    assert first.evidence.evidence_id == second.evidence.evidence_id
    assert first.evidence == second.evidence


@pytest.mark.parametrize(
    "change",
    [
        {"head_sha": _MERGE_SHA, "requested_sha": _MERGE_SHA, "observed_sha": _MERGE_SHA,
         "tested_sha": _MERGE_SHA},
        {"base_sha": _MERGE_SHA},
        {"contract_fingerprint": _OTHER_CONTRACT},
        {"freshness_boundary": "main@deadbeef"},
        {"observed_at": "2026-08-06T05:00:00Z"},
        {"repository_identity": _identity(repository="agent-os-fork")},
    ],
)
def test_any_observed_difference_changes_evidence_identity(change) -> None:
    baseline = prepare_repository_state_evidence(_observation())
    changed = prepare_repository_state_evidence(_observation(**change))

    assert changed.evidence.evidence_id != baseline.evidence.evidence_id


def test_evidence_round_trips_without_drift() -> None:
    original = prepare_repository_state_evidence(_observation()).evidence

    payload = repository_state_evidence_to_dict(original)
    rebuilt = repository_state_evidence_from_dict(
        json.loads(json.dumps(payload, sort_keys=True))
    )

    assert rebuilt == original
    assert rebuilt.evidence_id == original.evidence_id
    assert repository_state_evidence_to_dict(rebuilt) == payload
    assert rebuilt.execution_authorized is False
    assert rebuilt.side_effects_performed is False


def test_round_trip_preserves_optional_sha_absence() -> None:
    original = prepare_repository_state_evidence(
        _observation(tested_sha=None, requested_ref=None, requested_sha=None)
    ).evidence

    rebuilt = repository_state_evidence_from_dict(
        repository_state_evidence_to_dict(original)
    )

    assert rebuilt.tested_sha is None
    assert rebuilt.requested_ref is None
    assert rebuilt.requested_sha is None
    assert rebuilt == original


def test_round_trip_rejects_a_tampered_identity() -> None:
    payload = repository_state_evidence_to_dict(
        prepare_repository_state_evidence(_observation()).evidence
    )
    payload["head_sha"] = _MERGE_SHA

    with pytest.raises(ValueError, match="evidence_id does not match"):
        repository_state_evidence_from_dict(payload)


def test_round_trip_rejects_authority_escalation() -> None:
    payload = repository_state_evidence_to_dict(
        prepare_repository_state_evidence(_observation()).evidence
    )

    with pytest.raises(ValueError, match="execution_authorized"):
        repository_state_evidence_from_dict({**payload, "execution_authorized": True})
    with pytest.raises(ValueError, match="side_effects_performed"):
        repository_state_evidence_from_dict(
            {**payload, "side_effects_performed": True}
        )


def test_round_trip_rejects_unknown_and_missing_fields() -> None:
    payload = repository_state_evidence_to_dict(
        prepare_repository_state_evidence(_observation()).evidence
    )

    with pytest.raises(ValueError, match="unsupported field"):
        repository_state_evidence_from_dict({**payload, "surprise": 1})

    incomplete = dict(payload)
    incomplete.pop("head_sha")
    with pytest.raises(ValueError, match="missing field"):
        repository_state_evidence_from_dict(incomplete)

    with pytest.raises(ValueError, match="must be a mapping"):
        repository_state_evidence_from_dict(["not", "a", "mapping"])


def test_serializer_rejects_a_foreign_object() -> None:
    with pytest.raises(TypeError, match="RepositoryStateEvidence"):
        repository_state_evidence_to_dict(_observation())


# --------------------------------------------------------------------------
# Observation input contract.
# --------------------------------------------------------------------------


def test_malformed_sha_observation_fails_closed() -> None:
    result = prepare_repository_state_evidence(_observation(head_sha="not-a-sha"))

    assert result.status is RepositoryStageStatus.INVALID
    assert result.reason_codes == (REPOSITORY_OBSERVATION_REJECTED,)
    assert result.evidence is None
    assert result.validation is None


def test_malformed_contract_fingerprint_fails_closed() -> None:
    result = prepare_repository_state_evidence(
        _observation(contract_fingerprint="short")
    )

    assert result.status is RepositoryStageStatus.INVALID
    assert result.evidence is None


def test_every_repository_fact_must_be_stated_explicitly() -> None:
    for omitted in (
        "requested_ref",
        "requested_sha",
        "tested_sha",
        "pushed_sha",
        "proposed_pr_sha",
        "synthetic_merge_sha",
        "external_build_sha",
    ):
        values = {
            field.name: getattr(_observation(), field.name)
            for field in _observation().__dataclass_fields__.values()
            if field.init
        }
        values.pop(omitted)
        with pytest.raises(TypeError):
            RepositoryObservation(**values)


@pytest.mark.parametrize(
    "change",
    [
        {"repository_identity": {"owner": "blummer92"}},
        {"evidence_type": "branch-head"},
        {"worktree_state": "clean"},
        {"base_ref": "   "},
        {"head_ref": "agent/\n752"},
        {"producer_adapter": 7},
        {"correlation_id": True},
        {"worktree_reason_codes": "worktree.dirty"},
    ],
)
def test_observation_rejects_non_canonical_input(change) -> None:
    with pytest.raises((TypeError, ValueError)):
        _observation(**change)


def test_prepare_rejects_a_non_observation_input() -> None:
    with pytest.raises(TypeError, match="RepositoryObservation"):
        prepare_repository_state_evidence({"head_sha": _HEAD_SHA})


# --------------------------------------------------------------------------
# No authority escalation and no side effects.
# --------------------------------------------------------------------------


def test_observation_and_result_never_authorize_execution() -> None:
    observation = _observation()
    result = prepare_repository_state_evidence(observation)

    assert observation.execution_authorized is False
    assert observation.side_effects_performed is False
    assert result.execution_authorized is False
    assert result.side_effects_performed is False
    assert result.evidence.execution_authorized is False
    assert result.evidence.side_effects_performed is False
    assert result.validation.execution_authorized is False
    assert result.validation.side_effects_performed is False

    # The authority fields are init=False, so no caller can set them at all.
    with pytest.raises(ValueError, match="init=False"):
        replace(result, execution_authorized=True)
    with pytest.raises(ValueError, match="init=False"):
        replace(observation, side_effects_performed=True)


def test_result_invariants_cannot_be_bypassed() -> None:
    valid = prepare_repository_state_evidence(_observation())

    with pytest.raises(ValueError, match="inseparable"):
        RepositoryStageResult(
            status=RepositoryStageStatus.VALID,
            evidence=valid.evidence,
            validation=None,
        )
    with pytest.raises(ValueError, match="only an invalid result"):
        RepositoryStageResult(
            status=RepositoryStageStatus.VALID, evidence=None, validation=None
        )
    with pytest.raises(ValueError, match="canonical validation outcome"):
        RepositoryStageResult(
            status=RepositoryStageStatus.STALE,
            evidence=valid.evidence,
            validation=valid.validation,
        )


_PROHIBITED_MODULES = frozenset(
    {
        "os",
        "io",
        "pathlib",
        "shutil",
        "socket",
        "ssl",
        "subprocess",
        "tempfile",
        "urllib",
        "urllib.request",
        "http",
        "http.client",
        "requests",
        "git",
        "github",
    }
)

_PROHIBITED_CALLS = frozenset({"open", "system", "run", "Popen", "connect", "write"})


def test_repository_stage_reaches_no_io_or_execution_surface() -> None:
    """Static proof of the read-only boundary this stage claims."""
    source = Path(inspect.getfile(repository_stage)).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            imported.add(node.module or "")
        elif isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Attribute):
                called.add(function.attr)
            elif isinstance(function, ast.Name):
                called.add(function.id)

    assert imported & _PROHIBITED_MODULES == set()
    assert called & _PROHIBITED_CALLS == set()
