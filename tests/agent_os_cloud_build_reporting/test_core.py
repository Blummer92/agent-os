"""Tests for the pure-local Cloud Build reporting core (issue #685)."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scripts.agent_os_cloud_build_reporting import (
    CloudBuildCommentProjection,
    CloudBuildEvidenceError,
    CloudBuildResultEvidence,
    OverallResult,
    PullRequestResolutionCandidate,
    PullRequestResolutionResult,
    PullRequestState,
    ResolutionStatus,
    compute_stable_marker,
    evidence_semantic_identity,
    is_same_build,
    normalize_cloud_build_evidence,
    render_comment_projection,
    resolve_pull_request,
    serialize_projection,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "agent_os_cloud_build_reporting"

SHA_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SHA_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
REPO = "Blummer92/agent-os"


def _load_json(name: str) -> list[dict]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _success_evidence(**overrides) -> CloudBuildResultEvidence:
    kwargs = dict(
        build_id="build-1",
        tested_sha=SHA_A,
        repository=REPO,
        overall_result="success",
        terminal=True,
        source_complete=True,
        failed_step="none",
        exit_code=0,
    )
    kwargs.update(overrides)
    return normalize_cloud_build_evidence(**kwargs)


def _candidate(**overrides) -> PullRequestResolutionCandidate:
    kwargs = dict(
        repository=REPO,
        pull_request_number=1,
        head_sha=SHA_A,
        state=PullRequestState.OPEN,
        evidence_source="lookup",
    )
    kwargs.update(overrides)
    return PullRequestResolutionCandidate(**kwargs)


# ---------------------------------------------------------------------------
# Evidence: terminal and non-terminal states
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", _load_json("evidence_cases.json"), ids=lambda c: c["name"])
def test_evidence_cases_construct_cleanly(case: dict) -> None:
    evidence = normalize_cloud_build_evidence(**case["kwargs"])
    assert evidence.overall_result.value == case["kwargs"]["overall_result"]
    assert evidence.repository == REPO.lower()


def test_unavailable_failed_step_and_exit_code_preserved() -> None:
    evidence = normalize_cloud_build_evidence(
        build_id="build-2",
        tested_sha=SHA_A,
        repository=REPO,
        overall_result="failure",
        terminal=True,
        source_complete=True,
        failed_step=None,
        exit_code=None,
    )
    assert evidence.failed_step is None
    assert evidence.exit_code is None


def test_contradictory_result_and_exit_code_rejected() -> None:
    with pytest.raises(CloudBuildEvidenceError):
        normalize_cloud_build_evidence(
            build_id="build-3",
            tested_sha=SHA_A,
            repository=REPO,
            overall_result="failure",
            terminal=True,
            source_complete=True,
            exit_code=0,
        )


def test_exit_code_zero_requires_terminal() -> None:
    with pytest.raises(CloudBuildEvidenceError):
        normalize_cloud_build_evidence(
            build_id="build-4",
            tested_sha=SHA_A,
            repository=REPO,
            overall_result="pending",
            terminal=False,
            source_complete=True,
            exit_code=0,
        )


def test_failed_step_none_requires_success() -> None:
    with pytest.raises(CloudBuildEvidenceError):
        normalize_cloud_build_evidence(
            build_id="build-5",
            tested_sha=SHA_A,
            repository=REPO,
            overall_result="failure",
            terminal=True,
            source_complete=True,
            failed_step="none",
        )


def test_terminal_result_requires_terminal_flag() -> None:
    with pytest.raises(CloudBuildEvidenceError):
        normalize_cloud_build_evidence(
            build_id="build-6",
            tested_sha=SHA_A,
            repository=REPO,
            overall_result="success",
            terminal=False,
            source_complete=True,
        )


def test_pending_result_requires_non_terminal_flag() -> None:
    with pytest.raises(CloudBuildEvidenceError):
        normalize_cloud_build_evidence(
            build_id="build-7",
            tested_sha=SHA_A,
            repository=REPO,
            overall_result="pending",
            terminal=True,
            source_complete=True,
        )


def test_unsupported_overall_result_rejected() -> None:
    with pytest.raises(CloudBuildEvidenceError):
        normalize_cloud_build_evidence(
            build_id="build-8",
            tested_sha=SHA_A,
            repository=REPO,
            overall_result="not-a-real-result",
            terminal=True,
            source_complete=True,
        )


@pytest.mark.parametrize(
    "bad_sha",
    ["", "short", SHA_A[:39], SHA_A + "a", SHA_A.upper(), "g" * 40],
)
def test_partial_or_malformed_sha_rejected(bad_sha: str) -> None:
    with pytest.raises(CloudBuildEvidenceError):
        normalize_cloud_build_evidence(
            build_id="build-9",
            tested_sha=bad_sha,
            repository=REPO,
            overall_result="success",
            terminal=True,
            source_complete=True,
            failed_step="none",
            exit_code=0,
        )


# ---------------------------------------------------------------------------
# PR resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", _load_json("pr_resolution_cases.json"), ids=lambda c: c["name"])
def test_pr_resolution_cases(case: dict) -> None:
    evidence = _success_evidence(tested_sha=case["tested_sha"], repository=case["repository"])
    candidates = [
        PullRequestResolutionCandidate(
            repository=c["repository"],
            pull_request_number=c["pull_request_number"],
            head_sha=c["head_sha"],
            state=PullRequestState(c["state"]),
            evidence_source=c["evidence_source"],
        )
        for c in case["candidates"]
    ]
    result = resolve_pull_request(
        evidence,
        authoritative_pr_number=case["authoritative_pr_number"],
        candidates=candidates,
    )
    assert result.status.value == case["expect_status"]
    if "expect_pull_request_number" in case:
        assert result.pull_request_number == case["expect_pull_request_number"]
    else:
        assert result.pull_request_number is None
    assert result.reason_codes


def test_closed_pr_reason_code() -> None:
    evidence = _success_evidence()
    result = resolve_pull_request(
        evidence,
        candidates=[_candidate(state=PullRequestState.CLOSED)],
    )
    assert result.status == ResolutionStatus.SKIPPED
    assert "resolution.closed-candidate" in result.reason_codes


def test_conflicting_authoritative_and_candidate_evidence() -> None:
    evidence = _success_evidence()
    result = resolve_pull_request(
        evidence,
        authoritative_pr_number=1,
        candidates=[
            _candidate(pull_request_number=1),
            _candidate(pull_request_number=2, evidence_source="other-lookup"),
        ],
    )
    assert result.status == ResolutionStatus.MANUAL_REVIEW
    assert "resolution.conflicting-evidence" in result.reason_codes


def test_incomplete_source_evidence_is_invalid() -> None:
    evidence = normalize_cloud_build_evidence(
        build_id="build-10",
        tested_sha=SHA_A,
        repository=REPO,
        overall_result="unavailable",
        terminal=True,
        source_complete=False,
    )
    result = resolve_pull_request(evidence, candidates=[_candidate()])
    assert result.status == ResolutionStatus.INVALID
    assert "resolution.incomplete-evidence" in result.reason_codes


def test_malformed_evidence_is_invalid() -> None:
    evidence = normalize_cloud_build_evidence(
        build_id="build-11",
        tested_sha=SHA_A,
        repository=REPO,
        overall_result="malformed",
        terminal=False,
        source_complete=True,
    )
    result = resolve_pull_request(evidence, candidates=[_candidate()])
    assert result.status == ResolutionStatus.INVALID
    assert "resolution.malformed-evidence" in result.reason_codes


def test_duplicate_candidate_identities_are_manual_review() -> None:
    evidence = _success_evidence()
    result = resolve_pull_request(
        evidence,
        candidates=[_candidate(), _candidate(evidence_source="duplicate-lookup")],
    )
    assert result.status == ResolutionStatus.MANUAL_REVIEW
    assert "resolution.duplicate-candidate" in result.reason_codes


def test_never_resolves_from_issue_number_alone() -> None:
    # An authoritative "PR number" that happens to equal an issue number but
    # has no matching supplied candidate must never resolve automatically.
    evidence = _success_evidence()
    result = resolve_pull_request(evidence, authoritative_pr_number=685, candidates=[])
    assert result.status == ResolutionStatus.MANUAL_REVIEW
    assert result.pull_request_number is None


# ---------------------------------------------------------------------------
# Rendering, marker determinism, and serialization
# ---------------------------------------------------------------------------


def test_deterministic_marker_for_same_build() -> None:
    evidence_a = _success_evidence()
    evidence_b = _success_evidence()
    assert compute_stable_marker(evidence_a) == compute_stable_marker(evidence_b)
    assert is_same_build(evidence_a, evidence_b)


def test_marker_differs_for_different_build() -> None:
    evidence_a = _success_evidence(build_id="build-a")
    evidence_b = _success_evidence(build_id="build-b")
    assert compute_stable_marker(evidence_a) != compute_stable_marker(evidence_b)
    assert not is_same_build(evidence_a, evidence_b)


def test_same_build_replay_produces_identical_projection() -> None:
    evidence = _success_evidence()
    result = resolve_pull_request(evidence, candidates=[_candidate()])
    projection_1 = render_comment_projection(evidence, result)
    projection_2 = render_comment_projection(evidence, result)
    assert serialize_projection(projection_1) == serialize_projection(projection_2)


def test_canonical_serialization_is_input_order_independent() -> None:
    evidence_1 = _success_evidence(trigger_id="t1", invocation_id="i1")
    evidence_2 = _success_evidence(trigger_id="t1", invocation_id="i1")
    result_1 = resolve_pull_request(
        evidence_1, candidates=[_candidate(), _candidate(pull_request_number=2, head_sha=SHA_B, state=PullRequestState.CLOSED)]
    )
    result_2 = resolve_pull_request(
        evidence_2,
        candidates=[_candidate(pull_request_number=2, head_sha=SHA_B, state=PullRequestState.CLOSED), _candidate()],
    )
    projection_1 = render_comment_projection(evidence_1, result_1)
    projection_2 = render_comment_projection(evidence_2, result_2)
    assert serialize_projection(projection_1) == serialize_projection(projection_2)


def test_reason_codes_have_stable_ordering() -> None:
    codes = ("resolution.sha-mismatch", "resolution.repository-mismatch")
    result = PullRequestResolutionResult(
        status=ResolutionStatus.SKIPPED, pull_request_number=None, reason_codes=codes
    )
    assert result.reason_codes == tuple(sorted(codes))


def test_rendered_body_states_supplemental_and_non_authorizing() -> None:
    evidence = _success_evidence()
    result = resolve_pull_request(evidence, candidates=[_candidate()])
    projection = render_comment_projection(evidence, result)
    assert "does not authorize" in projection.rendered_body
    assert projection.side_effects_performed is False
    assert projection.execution_authorized is False


def test_manual_review_reasons_empty_when_resolved() -> None:
    evidence = _success_evidence()
    result = resolve_pull_request(evidence, candidates=[_candidate()])
    projection = render_comment_projection(evidence, result)
    assert projection.manual_review_reasons == ()


def test_manual_review_reasons_populated_when_not_resolved() -> None:
    evidence = _success_evidence()
    result = resolve_pull_request(evidence, candidates=[])
    projection = render_comment_projection(evidence, result)
    assert projection.manual_review_reasons


# ---------------------------------------------------------------------------
# Redaction and hostile/oversized input handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "secret_bearing_step",
    [
        "Bearer sk-1234567890abcdef1234567890abcdef",
        "token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        "authorization: Basic dXNlcjpwYXNz",
        "password=hunter2-super-secret-value",
        "AKIAABCDEFGHIJKLMNOP",
        "https://storage.googleapis.com/x?X-Goog-Signature=abc123def456",
    ],
)
def test_secret_like_failed_step_is_redacted(secret_bearing_step: str) -> None:
    evidence = normalize_cloud_build_evidence(
        build_id="build-secret",
        tested_sha=SHA_A,
        repository=REPO,
        overall_result="failure",
        terminal=True,
        source_complete=True,
        failed_step=secret_bearing_step,
    )
    result = resolve_pull_request(evidence, candidates=[])
    projection = render_comment_projection(evidence, result)
    assert secret_bearing_step not in projection.rendered_body
    assert "[REDACTED]" in projection.failed_step or "[REDACTED]" in projection.rendered_body


def test_oversized_string_rejected_at_construction() -> None:
    with pytest.raises(CloudBuildEvidenceError):
        normalize_cloud_build_evidence(
            build_id="x" * 10_000,
            tested_sha=SHA_A,
            repository=REPO,
            overall_result="success",
            terminal=True,
            source_complete=True,
            failed_step="none",
            exit_code=0,
        )


def test_control_characters_rejected() -> None:
    with pytest.raises(CloudBuildEvidenceError):
        normalize_cloud_build_evidence(
            build_id="build\x00with-null",
            tested_sha=SHA_A,
            repository=REPO,
            overall_result="success",
            terminal=True,
            source_complete=True,
            failed_step="none",
            exit_code=0,
        )


def test_hostile_object_type_rejected_for_exit_code() -> None:
    with pytest.raises(CloudBuildEvidenceError):
        normalize_cloud_build_evidence(
            build_id="build-hostile",
            tested_sha=SHA_A,
            repository=REPO,
            overall_result="failure",
            terminal=True,
            source_complete=True,
            exit_code="1",  # type: ignore[arg-type]
        )


def test_bool_rejected_as_exit_code() -> None:
    with pytest.raises(CloudBuildEvidenceError):
        normalize_cloud_build_evidence(
            build_id="build-bool",
            tested_sha=SHA_A,
            repository=REPO,
            overall_result="success",
            terminal=True,
            source_complete=True,
            exit_code=True,  # type: ignore[arg-type]
        )


def test_long_failed_step_is_truncated_in_rendering() -> None:
    evidence = normalize_cloud_build_evidence(
        build_id="build-long",
        tested_sha=SHA_A,
        repository=REPO,
        overall_result="failure",
        terminal=True,
        source_complete=True,
        failed_step="x" * 500,
    )
    result = resolve_pull_request(evidence, candidates=[])
    projection = render_comment_projection(evidence, result)
    assert "truncated" in projection.failed_step


# ---------------------------------------------------------------------------
# Immutability, no I/O, and fixed authority flags
# ---------------------------------------------------------------------------


def test_models_are_frozen() -> None:
    evidence = _success_evidence()
    with pytest.raises(FrozenInstanceError):
        evidence.build_id = "changed"  # type: ignore[misc]

    candidate = _candidate()
    with pytest.raises(FrozenInstanceError):
        candidate.pull_request_number = 999  # type: ignore[misc]

    result = resolve_pull_request(evidence, candidates=[_candidate()])
    with pytest.raises(FrozenInstanceError):
        result.status = ResolutionStatus.INVALID  # type: ignore[misc]

    projection = render_comment_projection(evidence, result)
    with pytest.raises(FrozenInstanceError):
        projection.rendered_body = "changed"  # type: ignore[misc]


def test_inputs_are_not_mutated_by_resolution_or_rendering() -> None:
    evidence = _success_evidence()
    candidates = [_candidate()]
    before = tuple(candidates)
    result = resolve_pull_request(evidence, candidates=candidates)
    render_comment_projection(evidence, result)
    assert tuple(candidates) == before


def test_all_authority_and_side_effect_flags_are_false() -> None:
    evidence = _success_evidence()
    candidate = _candidate()
    result = resolve_pull_request(evidence, candidates=[candidate])
    projection = render_comment_projection(evidence, result)

    assert evidence.execution_authorized is False
    assert evidence.side_effects_performed is False
    assert result.execution_authorized is False
    assert result.side_effects_performed is False
    assert projection.execution_authorized is False
    assert projection.side_effects_performed is False


def test_no_module_level_io_imports() -> None:
    import scripts.agent_os_cloud_build_reporting.core as core_module

    lines = Path(core_module.__file__).read_text(encoding="utf-8").splitlines()
    import_lines = [line for line in lines if line.startswith(("import ", "from "))]
    forbidden_modules = ("socket", "subprocess", "requests", "urllib", "http", "os")
    for line in import_lines:
        for forbidden in forbidden_modules:
            assert not line.startswith(f"import {forbidden}") and not line.startswith(
                f"from {forbidden}"
            ), line


def test_evidence_semantic_identity_is_bounded_tuple() -> None:
    evidence = _success_evidence()
    identity = evidence_semantic_identity(evidence)
    assert isinstance(identity, tuple)
    assert len(identity) == 4


# ---------------------------------------------------------------------------
# NO-GO repair: secret-safe public projection and serialization (Fix 1)
# ---------------------------------------------------------------------------

SECRET_LIKE_VALUES = [
    "Bearer sk-1234567890abcdef1234567890abcdef",
    "token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "api_key=sUpErSeCrEt1234567890",
    "password=hunter2-super-secret-value",
    "https://storage.googleapis.com/x?X-Goog-Signature=abc123def456",
    "/home/user/.ssh/id_rsa",
    "Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: boom",
]


@pytest.mark.parametrize("secret_value", SECRET_LIKE_VALUES)
def test_secret_like_build_id_is_sanitized_everywhere(secret_value: str) -> None:
    evidence = normalize_cloud_build_evidence(
        build_id=secret_value,
        tested_sha=SHA_A,
        repository=REPO,
        overall_result="success",
        terminal=True,
        source_complete=True,
        failed_step="none",
        exit_code=0,
    )
    result = resolve_pull_request(evidence, candidates=[_candidate()])
    projection = render_comment_projection(evidence, result)
    serialized = serialize_projection(projection)

    assert secret_value not in projection.build_id
    assert secret_value not in projection.rendered_body
    assert secret_value not in serialized


@pytest.mark.parametrize("secret_value", SECRET_LIKE_VALUES)
def test_secret_like_failed_step_is_sanitized_everywhere(secret_value: str) -> None:
    evidence = normalize_cloud_build_evidence(
        build_id="build-1",
        tested_sha=SHA_A,
        repository=REPO,
        overall_result="failure",
        terminal=True,
        source_complete=True,
        failed_step=secret_value,
    )
    result = resolve_pull_request(evidence, candidates=[])
    projection = render_comment_projection(evidence, result)
    serialized = serialize_projection(projection)

    assert secret_value not in projection.failed_step
    assert secret_value not in projection.rendered_body
    assert secret_value not in serialized


def test_oversized_build_id_is_bounded_in_projection_and_serialization() -> None:
    evidence = normalize_cloud_build_evidence(
        build_id="b" * 500,
        tested_sha=SHA_A,
        repository=REPO,
        overall_result="success",
        terminal=True,
        source_complete=True,
        failed_step="none",
        exit_code=0,
    )
    result = resolve_pull_request(evidence, candidates=[_candidate()])
    projection = render_comment_projection(evidence, result)
    serialized = serialize_projection(projection)

    assert "truncated" in projection.build_id
    assert len(projection.build_id) < 500
    assert "truncated" in serialized


def test_serialize_projection_never_contains_raw_supplied_secret() -> None:
    evidence = normalize_cloud_build_evidence(
        build_id="AKIAABCDEFGHIJKLMNOP",
        tested_sha=SHA_A,
        repository=REPO,
        overall_result="failure",
        terminal=True,
        source_complete=True,
        failed_step="authorization: Bearer eyJhbGciOiJIUzI1NiJ9.secretpayload",
    )
    result = resolve_pull_request(evidence, candidates=[])
    projection = render_comment_projection(evidence, result)
    serialized = serialize_projection(projection)

    assert "AKIAABCDEFGHIJKLMNOP" not in serialized
    assert "secretpayload" not in serialized
    assert json.loads(serialized)["build_id"] == projection.build_id


def test_repository_and_tested_sha_remain_exact_and_unredacted() -> None:
    evidence = _success_evidence()
    result = resolve_pull_request(evidence, candidates=[_candidate()])
    projection = render_comment_projection(evidence, result)
    assert projection.tested_sha == SHA_A
    assert evidence.repository == REPO.lower()


# ---------------------------------------------------------------------------
# NO-GO repair: bounded PR candidate intake (Fix 2)
# ---------------------------------------------------------------------------


class _CountingCandidates:
    """An effectively unbounded iterable that records items consumed."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.consumed = 0

    def __iter__(self):
        for index in range(self.total):
            self.consumed += 1
            yield _candidate(
                pull_request_number=index + 1,
                head_sha=SHA_B,
                state=PullRequestState.CLOSED,
                evidence_source=f"lookup-{index}",
            )


def test_zero_candidates_is_skipped() -> None:
    evidence = _success_evidence()
    result = resolve_pull_request(evidence, candidates=[])
    assert result.status == ResolutionStatus.SKIPPED


def test_one_candidate_resolves() -> None:
    evidence = _success_evidence()
    result = resolve_pull_request(evidence, candidates=[_candidate()])
    assert result.status == ResolutionStatus.RESOLVED


def test_exactly_maximum_candidates_is_not_rejected_for_size() -> None:
    from scripts.agent_os_cloud_build_reporting import MAX_PR_CANDIDATES

    evidence = _success_evidence()
    candidates = [
        _candidate(
            pull_request_number=index + 1,
            head_sha=SHA_B,
            state=PullRequestState.CLOSED,
            evidence_source=f"lookup-{index}",
        )
        for index in range(MAX_PR_CANDIDATES)
    ]
    result = resolve_pull_request(evidence, candidates=candidates)
    assert "resolution.too-many-candidates" not in result.reason_codes


def test_maximum_plus_one_candidates_fails_closed_with_stable_reason() -> None:
    from scripts.agent_os_cloud_build_reporting import MAX_PR_CANDIDATES

    evidence = _success_evidence()
    candidates = [
        _candidate(
            pull_request_number=index + 1,
            head_sha=SHA_B,
            state=PullRequestState.CLOSED,
            evidence_source=f"lookup-{index}",
        )
        for index in range(MAX_PR_CANDIDATES + 1)
    ]
    result = resolve_pull_request(evidence, candidates=candidates)
    assert result.status == ResolutionStatus.INVALID
    assert result.reason_codes == ("resolution.too-many-candidates",)
    # Deterministic reason ordering: repeated calls yield the identical tuple.
    assert resolve_pull_request(evidence, candidates=candidates).reason_codes == result.reason_codes


def test_generator_intake_stops_consuming_past_the_bound() -> None:
    from scripts.agent_os_cloud_build_reporting import MAX_PR_CANDIDATES

    evidence = _success_evidence()
    source = _CountingCandidates(MAX_PR_CANDIDATES + 1_000_000)
    result = resolve_pull_request(evidence, candidates=source)
    assert result.status == ResolutionStatus.INVALID
    assert result.reason_codes == ("resolution.too-many-candidates",)
    assert source.consumed == MAX_PR_CANDIDATES + 1


def test_hostile_unbounded_iterable_does_not_hang_or_exhaust() -> None:
    from scripts.agent_os_cloud_build_reporting import MAX_PR_CANDIDATES

    def infinite():
        index = 0
        while True:
            yield _candidate(
                pull_request_number=index + 1,
                head_sha=SHA_B,
                state=PullRequestState.CLOSED,
                evidence_source=f"lookup-{index}",
            )
            index += 1

    evidence = _success_evidence()
    result = resolve_pull_request(evidence, candidates=infinite())
    assert result.status == ResolutionStatus.INVALID
    assert result.reason_codes == ("resolution.too-many-candidates",)


def test_expired_terminal_result_requires_terminal_flag_true() -> None:
    evidence = normalize_cloud_build_evidence(
        build_id="build-expired-1",
        tested_sha=SHA_A,
        repository=REPO,
        overall_result="expired",
        terminal=True,
        source_complete=True,
        failed_step=None,
        exit_code=None,
    )
    assert evidence.overall_result == OverallResult.EXPIRED
    assert evidence.terminal is True


def test_expired_terminal_result_requires_terminal_flag_false_rejects() -> None:
    with pytest.raises(CloudBuildEvidenceError):
        normalize_cloud_build_evidence(
            build_id="build-expired-1",
            tested_sha=SHA_A,
            repository=REPO,
            overall_result="expired",
            terminal=False,
            source_complete=True,
        )


def test_expired_with_failed_step_rejected() -> None:
    with pytest.raises(CloudBuildEvidenceError):
        normalize_cloud_build_evidence(
            build_id="build-expired-1",
            tested_sha=SHA_A,
            repository=REPO,
            overall_result="expired",
            terminal=True,
            source_complete=True,
            failed_step="none",
            exit_code=None,
        )


def test_expired_with_exit_code_zero_rejected() -> None:
    with pytest.raises(CloudBuildEvidenceError):
        normalize_cloud_build_evidence(
            build_id="build-expired-1",
            tested_sha=SHA_A,
            repository=REPO,
            overall_result="expired",
            terminal=True,
            source_complete=True,
            failed_step=None,
            exit_code=0,
        )


def test_expired_preserves_deterministic_semantic_identity() -> None:
    evidence = normalize_cloud_build_evidence(
        build_id="build-expired-1",
        tested_sha=SHA_A,
        repository=REPO,
        overall_result="expired",
        terminal=True,
        source_complete=True,
    )
    identity_1 = evidence_semantic_identity(evidence)
    evidence_2 = normalize_cloud_build_evidence(
        build_id="build-expired-1",
        tested_sha=SHA_A,
        repository=REPO,
        overall_result="expired",
        terminal=True,
        source_complete=True,
    )
    identity_2 = evidence_semantic_identity(evidence_2)
    assert identity_1 == identity_2


def test_expired_rendering_preserves_literal_overall_result() -> None:
    evidence = normalize_cloud_build_evidence(
        build_id="build-expired-1",
        tested_sha=SHA_A,
        repository=REPO,
        overall_result="expired",
        terminal=True,
        source_complete=True,
    )
    result = resolve_pull_request(evidence, candidates=[_candidate()])
    assert result.status == ResolutionStatus.RESOLVED
    projection = render_comment_projection(evidence, result)
    assert "expired" in projection.rendered_body
    assert "result: expired" in projection.rendered_body


def test_expired_authority_and_side_effects_remain_false() -> None:
    evidence = normalize_cloud_build_evidence(
        build_id="build-expired-1",
        tested_sha=SHA_A,
        repository=REPO,
        overall_result="expired",
        terminal=True,
        source_complete=True,
    )
    assert evidence.execution_authorized is False
    assert evidence.side_effects_performed is False


def test_candidate_input_list_is_not_mutated() -> None:
    evidence = _success_evidence()
    candidates = [_candidate(), _candidate(pull_request_number=2, head_sha=SHA_B, state=PullRequestState.CLOSED)]
    before = list(candidates)
    resolve_pull_request(evidence, candidates=candidates)
    assert candidates == before
