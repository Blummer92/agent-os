"""AOS-AUTO1H verify-repo-state.sh stdout assembler tests (#1155, #1327)."""

from __future__ import annotations

import pytest

from scripts.agent_os_candidate_packet.repository_stage import (
    RepositoryObservation,
    RepositoryStageStatus,
    prepare_repository_state_evidence,
)
from scripts.agent_os_candidate_packet_live_input.repository_observation import (
    VerifierStdoutError,
    build_repository_observation_from_verifier_stdout,
    parse_verifier_stdout,
)
from scripts.agent_os_execution_capabilities import (
    RepositoryEvidenceType,
    RepositoryIdentity,
    WorktreeState,
)

_HEAD_SHA = "a" * 40
_BASE_SHA = "b" * 40


def _valid_stdout(
    *,
    head_ref: str = "agent/1155-live-candidate-input-adapter",
    head_sha: str = _HEAD_SHA,
    base_ref: str = "origin/main",
    base_sha: str = _BASE_SHA,
    changed_files: tuple[str, ...] = ("scripts/agent_os_candidate_packet_live_input/__init__.py",),
) -> str:
    lines = [
        f"HEAD_REF={head_ref}",
        f"HEAD_SHA={head_sha}",
        f"BASE_REF={base_ref}",
        f"BASE_SHA={base_sha}",
        "CHANGED_FILES_BEGIN",
        *changed_files,
        "CHANGED_FILES_END",
    ]
    return "\n".join(lines) + "\n"


def _identity(**overrides) -> RepositoryIdentity:
    values = dict(host="github.com", owner="Blummer92", repository="agent-os")
    values.update(overrides)
    return RepositoryIdentity(**values)


def _assemble(**overrides):
    values = dict(
        verifier_stdout=_valid_stdout(),
        producer_adapter="live-input-adapter",
        producer_adapter_version="0.1.0",
        correlation_id="issue-1155",
        repository_identity=_identity(),
        contract_fingerprint="3" * 64,
        observed_at="2026-08-15T00:10:00Z",
        freshness_boundary="main@1155",
        evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        requested_ref="agent/1155-live-candidate-input-adapter",
        requested_sha=_HEAD_SHA,
        tested_sha=None,
        pushed_sha=None,
        proposed_pr_sha=None,
        synthetic_merge_sha=None,
        external_build_sha=None,
    )
    values.update(overrides)
    return build_repository_observation_from_verifier_stdout(**values)


# --------------------------------------------------------------------------
# Happy path.
# --------------------------------------------------------------------------


def test_parser_preserves_documented_raw_verifier_base_ref() -> None:
    evidence = parse_verifier_stdout(_valid_stdout())
    assert evidence.base_ref == "origin/main"


def test_valid_stdout_plus_explicit_fields_produces_canonical_observation() -> None:
    observation = _assemble()

    assert isinstance(observation, RepositoryObservation)
    assert observation.head_ref == "agent/1155-live-candidate-input-adapter"
    assert observation.head_sha == _HEAD_SHA
    assert observation.base_ref == "main"
    assert observation.base_sha == _BASE_SHA
    assert observation.observed_sha == _HEAD_SHA


def test_canonicalized_base_ref_validates_against_short_branch_vocabulary() -> None:
    observation = _assemble(tested_sha=_HEAD_SHA)

    result = prepare_repository_state_evidence(
        observation,
        expected_base_ref="main",
        expected_head_ref="agent/1155-live-candidate-input-adapter",
        expected_head_sha=_HEAD_SHA,
        expected_requested_sha=_HEAD_SHA,
        expected_contract_fingerprint="3" * 64,
    )

    assert result.status is RepositoryStageStatus.VALID
    assert "ref.base-mismatch" not in result.reason_codes


def test_worktree_state_is_exactly_clean() -> None:
    observation = _assemble()
    assert observation.worktree_state is WorktreeState.CLEAN


def test_empty_changed_files_block_still_parses() -> None:
    observation = _assemble(verifier_stdout=_valid_stdout(changed_files=()))
    assert observation.head_sha == _HEAD_SHA


# --------------------------------------------------------------------------
# Caller-supplied fields stay exactly caller-supplied; no inference.
# --------------------------------------------------------------------------


def test_optional_unobserved_shas_remain_exactly_caller_provided() -> None:
    observation = _assemble(
        tested_sha="c" * 40,
        pushed_sha="d" * 40,
        proposed_pr_sha="e" * 40,
        synthetic_merge_sha="f" * 40,
        external_build_sha="1" * 40,
    )

    assert observation.tested_sha == "c" * 40
    assert observation.pushed_sha == "d" * 40
    assert observation.proposed_pr_sha == "e" * 40
    assert observation.synthetic_merge_sha == "f" * 40
    assert observation.external_build_sha == "1" * 40


def test_optional_unobserved_shas_default_to_none_only_when_caller_passes_none() -> None:
    observation = _assemble()

    assert observation.tested_sha is None
    assert observation.pushed_sha is None
    assert observation.proposed_pr_sha is None
    assert observation.synthetic_merge_sha is None
    assert observation.external_build_sha is None


def test_evidence_type_is_never_inferred_it_is_exactly_what_the_caller_passed() -> None:
    observation = _assemble(evidence_type=RepositoryEvidenceType.UNCOMMITTED_WORKTREE)
    assert observation.evidence_type is RepositoryEvidenceType.UNCOMMITTED_WORKTREE


# --------------------------------------------------------------------------
# Missing caller-supplied fields fail -- no default is silently substituted.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name",
    (
        "producer_adapter",
        "producer_adapter_version",
        "correlation_id",
        "repository_identity",
        "contract_fingerprint",
        "observed_at",
        "freshness_boundary",
        "evidence_type",
        "requested_ref",
        "requested_sha",
        "tested_sha",
        "pushed_sha",
        "proposed_pr_sha",
        "synthetic_merge_sha",
        "external_build_sha",
    ),
)
def test_missing_required_caller_field_raises(field_name: str) -> None:
    values = dict(
        verifier_stdout=_valid_stdout(),
        producer_adapter="live-input-adapter",
        producer_adapter_version="0.1.0",
        correlation_id="issue-1155",
        repository_identity=_identity(),
        contract_fingerprint="3" * 64,
        observed_at="2026-08-15T00:10:00Z",
        freshness_boundary="main@1155",
        evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        requested_ref="agent/1155-live-candidate-input-adapter",
        requested_sha=_HEAD_SHA,
        tested_sha=None,
        pushed_sha=None,
        proposed_pr_sha=None,
        synthetic_merge_sha=None,
        external_build_sha=None,
    )
    del values[field_name]

    with pytest.raises(TypeError):
        build_repository_observation_from_verifier_stdout(**values)


# --------------------------------------------------------------------------
# Malformed / incomplete / duplicate / ambiguous verifier stdout fails closed.
# --------------------------------------------------------------------------


def test_missing_verifier_field_fails_closed() -> None:
    stdout = "\n".join(
        [
            "HEAD_REF=main",
            "HEAD_SHA=" + _HEAD_SHA,
            "CHANGED_FILES_BEGIN",
            "CHANGED_FILES_END",
        ]
    )
    with pytest.raises(VerifierStdoutError):
        parse_verifier_stdout(stdout)


def test_missing_changed_files_markers_fails_closed() -> None:
    stdout = "\n".join(
        [
            "HEAD_REF=main",
            f"HEAD_SHA={_HEAD_SHA}",
            "BASE_REF=origin/main",
            f"BASE_SHA={_BASE_SHA}",
        ]
    )
    with pytest.raises(VerifierStdoutError):
        parse_verifier_stdout(stdout)


def test_duplicate_verifier_keys_fail_closed() -> None:
    stdout = "\n".join(
        [
            "HEAD_REF=main",
            "HEAD_REF=other",
            f"HEAD_SHA={_HEAD_SHA}",
            "BASE_REF=origin/main",
            f"BASE_SHA={_BASE_SHA}",
            "CHANGED_FILES_BEGIN",
            "CHANGED_FILES_END",
        ]
    )
    with pytest.raises(VerifierStdoutError):
        parse_verifier_stdout(stdout)


def test_unexpected_verifier_key_fails_closed() -> None:
    stdout = "\n".join(
        [
            "HEAD_REF=main",
            f"HEAD_SHA={_HEAD_SHA}",
            "BASE_REF=origin/main",
            f"BASE_SHA={_BASE_SHA}",
            "UNEXPECTED_KEY=surprise",
            "CHANGED_FILES_BEGIN",
            "CHANGED_FILES_END",
        ]
    )
    with pytest.raises(VerifierStdoutError):
        parse_verifier_stdout(stdout)


@pytest.mark.parametrize(
    "base_ref",
    (
        "main",
        "upstream/main",
        "origin/",
        "origin//main",
        "origin/origin/main",
        "origin/refs/heads/main",
    ),
)
def test_assembler_rejects_noncanonical_verifier_base_ref_forms(base_ref: str) -> None:
    with pytest.raises(VerifierStdoutError):
        _assemble(verifier_stdout=_valid_stdout(base_ref=base_ref))


@pytest.mark.parametrize(
    "bad_sha",
    (
        "not-hex-and-wrong-length",
        "a" * 39,
        "a" * 41,
        "g" * 40,
        "",
    ),
)
def test_malformed_sha_fails_closed(bad_sha: str) -> None:
    with pytest.raises(VerifierStdoutError):
        parse_verifier_stdout(_valid_stdout(head_sha=bad_sha))


def test_malformed_ref_fails_closed() -> None:
    with pytest.raises(VerifierStdoutError):
        parse_verifier_stdout(_valid_stdout(head_ref=""))


def test_non_string_stdout_raises_type_error() -> None:
    with pytest.raises(TypeError):
        parse_verifier_stdout(None)  # type: ignore[arg-type]


def test_malformed_verifier_stdout_propagates_through_the_assembler() -> None:
    with pytest.raises(VerifierStdoutError):
        _assemble(verifier_stdout="garbage, not a verifier report")
