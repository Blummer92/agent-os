"""Fixture-first regression coverage for lifecycle_stage_acquisition.py (#3433).

Covers the full #3433 evidence contract without network access:

- normal evidence: one verified draft PR, one verified ready PR, one verified
  merged PR with the issue still open, and a closed issue;
- missing or ambiguous evidence: no PRs, incomplete enumeration, competing
  claims, ambiguous bare references, closed-unmerged PRs, wrong-repository
  and wrong-issue PRs;
- currentness: changed issue revision, changed repository SHA, PR state
  changes between reads, partial API failure, pagination limits;
- architecture protection: existing ``LifecycleStage`` reuse, no competing
  state model, no scheduler/queue/router/approval authority, preserved
  fail-closed behavior.

A passing unit test here never proves production consumption; that proof
lives in test_lifecycle_stage_acquisition_integration.py.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.issue_operational_state import (
    IssueState,
    LifecycleStage,
)
from scripts.agent_os_issue_acceptance.lifecycle_stage_acquisition import (
    LIFECYCLE_ACQUISITION_REASON_CODES,
    REASON_ACQUIRED,
    REASON_CLOSED_UNMERGED_PR,
    REASON_CONFLICTING_PR_CLAIMS,
    REASON_INCOMPLETE_ENUMERATION,
    REASON_NO_VERIFIED_PR_LINEAGE,
    REASON_PR_LINKAGE_UNVERIFIABLE,
    REASON_PR_REPOSITORY_MISMATCH,
    LifecycleAcquisitionOutcome,
    LifecycleStageAcquisitionRequest,
    LifecycleStageAcquisitionResult,
    PrLineageEnumeration,
    VerifiedPrLineage,
    acquire_lifecycle_stage,
    acquisition_bindings_current,
    lifecycle_stage_from_acquisition,
)
from scripts.agent_os_issue_acceptance.live_candidate_evidence_reader import (
    REASON_MISSING_LIFECYCLE_STAGE,
    LiveCandidateEvidence,
    LiveCandidateEvidenceReader,
)

REPOSITORY = "Blummer92/agent-os"
ISSUE_NUMBER = 3433
SOURCE_REVISION = "9" * 40
ISSUE_REVISION = "github-issue-v1:" + "a" * 64
OBSERVED_AT = "2026-10-08T15:00:00Z"

MODULE_PATH = Path(__file__).resolve().parents[2] / (
    "scripts/agent_os_issue_acceptance/lifecycle_stage_acquisition.py"
)


def pr_claim(number: int = 1201, **changes: object) -> VerifiedPrLineage:
    base: dict[str, object] = dict(
        pull_request_number=number,
        repository=REPOSITORY,
        is_open=True,
        is_draft=False,
        is_merged=False,
        head_sha="b" * 40,
        branch="agent/3433-lifecycle-stage-acquisition",
        pr_title="Implement #3433",
        pr_body="Implements the canonical lifecycle-stage acquirer.\n\nCloses #3433",
        observed_at=OBSERVED_AT,
    )
    base.update(changes)
    return VerifiedPrLineage(**base)  # type: ignore[arg-type]


def complete_enumeration(note: str = "all pages consumed; total matched") -> PrLineageEnumeration:
    return PrLineageEnumeration(complete=True, enumeration_note=note)


def incomplete_enumeration(note: str = "pagination limit reached") -> PrLineageEnumeration:
    return PrLineageEnumeration(complete=False, enumeration_note=note)


def acquisition_request(**changes: object) -> LifecycleStageAcquisitionRequest:
    base: dict[str, object] = dict(
        repository=REPOSITORY,
        issue_number=ISSUE_NUMBER,
        issue_state=IssueState.OPEN,
        issue_source_revision=ISSUE_REVISION,
        source_revision=SOURCE_REVISION,
        observed_at=OBSERVED_AT,
        pr_lineage=(),
        lineage_enumeration=complete_enumeration(),
    )
    base.update(changes)
    return LifecycleStageAcquisitionRequest(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Normal evidence
# ---------------------------------------------------------------------------


def test_open_issue_with_verified_draft_pr_acquires_draft_pr() -> None:
    result = acquire_lifecycle_stage(
        acquisition_request(pr_lineage=(pr_claim(is_draft=True),))
    )

    assert result.outcome is LifecycleAcquisitionOutcome.ACQUIRED
    assert type(result.lifecycle_stage) is LifecycleStage
    assert result.lifecycle_stage is LifecycleStage.DRAFT_PR
    assert result.reason_codes == (REASON_ACQUIRED,)
    assert result.verified_claims == (1201,)
    assert result.result_id.startswith("lifecycle-stage-acquisition:")


def test_open_issue_with_verified_ready_pr_acquires_review() -> None:
    result = acquire_lifecycle_stage(acquisition_request(pr_lineage=(pr_claim(),)))

    assert result.outcome is LifecycleAcquisitionOutcome.ACQUIRED
    assert result.lifecycle_stage is LifecycleStage.REVIEW
    assert result.reason_codes == (REASON_ACQUIRED,)


def test_merged_pr_with_open_issue_acquires_merged() -> None:
    result = acquire_lifecycle_stage(
        acquisition_request(pr_lineage=(pr_claim(is_open=False, is_merged=True),))
    )

    assert result.outcome is LifecycleAcquisitionOutcome.ACQUIRED
    assert result.lifecycle_stage is LifecycleStage.MERGED
    # Issue closure remains a separate lifecycle fact: the stage is merged
    # even though the issue is still open.


def test_closed_issue_acquires_closed_without_lineage() -> None:
    result = acquire_lifecycle_stage(
        acquisition_request(
            issue_state=IssueState.CLOSED,
            lineage_enumeration=incomplete_enumeration("closed issue; lineage not read"),
        )
    )

    assert result.outcome is LifecycleAcquisitionOutcome.ACQUIRED
    assert result.lifecycle_stage is LifecycleStage.CLOSED


def test_acquisition_is_deterministic_on_identical_evidence() -> None:
    request = acquisition_request(pr_lineage=(pr_claim(),))

    first = acquire_lifecycle_stage(request)
    second = acquire_lifecycle_stage(request)

    assert first.result_id == second.result_id
    assert first.result_id.startswith("lifecycle-stage-acquisition:")


# ---------------------------------------------------------------------------
# Missing or ambiguous evidence
# ---------------------------------------------------------------------------


def test_no_pr_with_complete_enumeration_fails_closed_without_default_stage() -> None:
    result = acquire_lifecycle_stage(acquisition_request())

    assert result.outcome is LifecycleAcquisitionOutcome.UNAVAILABLE
    assert result.lifecycle_stage is None
    assert result.reason_codes == (REASON_NO_VERIFIED_PR_LINEAGE,)
    # The absence of a PR proves neither planning nor implementation.
    assert lifecycle_stage_from_acquisition(result) is None


def test_incomplete_enumeration_fails_closed() -> None:
    result = acquire_lifecycle_stage(
        acquisition_request(lineage_enumeration=incomplete_enumeration())
    )

    assert result.outcome is LifecycleAcquisitionOutcome.UNAVAILABLE
    assert result.lifecycle_stage is None
    assert result.reason_codes == (REASON_INCOMPLETE_ENUMERATION,)


def test_competing_pr_claims_require_manual_review() -> None:
    result = acquire_lifecycle_stage(
        acquisition_request(pr_lineage=(pr_claim(1201), pr_claim(1202, is_draft=True)))
    )

    assert result.outcome is LifecycleAcquisitionOutcome.MANUAL_REVIEW
    assert result.lifecycle_stage is None
    assert result.reason_codes == (REASON_CONFLICTING_PR_CLAIMS,)
    assert result.verified_claims == (1201, 1202)


def test_ambiguous_bare_reference_requires_manual_review() -> None:
    claim = pr_claim(pr_body="See #3433 for background; related work in progress.")

    result = acquire_lifecycle_stage(acquisition_request(pr_lineage=(claim,)))

    assert result.outcome is LifecycleAcquisitionOutcome.MANUAL_REVIEW
    assert result.reason_codes == (REASON_PR_LINKAGE_UNVERIFIABLE,)


def test_pr_linking_a_different_issue_requires_manual_review() -> None:
    claim = pr_claim(pr_body="Implements the acquirer.\n\nCloses #9999")

    result = acquire_lifecycle_stage(acquisition_request(pr_lineage=(claim,)))

    assert result.outcome is LifecycleAcquisitionOutcome.MANUAL_REVIEW
    assert result.reason_codes == (REASON_PR_LINKAGE_UNVERIFIABLE,)


def test_pr_from_wrong_repository_requires_manual_review() -> None:
    claim = pr_claim(
        repository="someone-else/other-repo",
        pr_body="Implements the acquirer.\n\nCloses #3433",
    )

    result = acquire_lifecycle_stage(acquisition_request(pr_lineage=(claim,)))

    assert result.outcome is LifecycleAcquisitionOutcome.MANUAL_REVIEW
    assert result.reason_codes == (REASON_PR_REPOSITORY_MISMATCH,)


def test_closed_unmerged_pr_requires_manual_review() -> None:
    claim = pr_claim(is_open=False, is_merged=False)

    result = acquire_lifecycle_stage(acquisition_request(pr_lineage=(claim,)))

    assert result.outcome is LifecycleAcquisitionOutcome.MANUAL_REVIEW
    assert result.reason_codes == (REASON_CLOSED_UNMERGED_PR,)


def test_malformed_request_fails_as_contract_violation() -> None:
    with pytest.raises(ValueError):
        acquisition_request(source_revision="not-a-sha")
    with pytest.raises(ValueError):
        acquisition_request(issue_source_revision="github-issue-v1:xyz")
    with pytest.raises(TypeError):
        acquire_lifecycle_stage(object())  # type: ignore[arg-type]


def test_duplicate_pr_numbers_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate pull request numbers"):
        acquisition_request(pr_lineage=(pr_claim(1201), pr_claim(1201, is_draft=True)))


def test_inconsistent_pr_facts_are_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be open"):
        pr_claim(is_open=True, is_merged=True)
    with pytest.raises(ValueError, match="must be open"):
        pr_claim(is_open=False, is_draft=True)


def test_complete_enumeration_requires_a_note() -> None:
    with pytest.raises(ValueError, match="non-empty note"):
        PrLineageEnumeration(complete=True, enumeration_note="")


# ---------------------------------------------------------------------------
# Currentness
# ---------------------------------------------------------------------------


def test_changed_issue_revision_invalidates_bindings() -> None:
    result = acquire_lifecycle_stage(acquisition_request(pr_lineage=(pr_claim(),)))
    changed_revision = "github-issue-v1:" + "f" * 64

    assert acquisition_bindings_current(
        result,
        issue_source_revision=ISSUE_REVISION,
        source_revision=SOURCE_REVISION,
    )
    assert not acquisition_bindings_current(
        result,
        issue_source_revision=changed_revision,
        source_revision=SOURCE_REVISION,
    )

    reacquired = acquire_lifecycle_stage(
        acquisition_request(
            pr_lineage=(pr_claim(),), issue_source_revision=changed_revision
        )
    )
    assert reacquired.result_id != result.result_id
    assert reacquired.issue_source_revision == changed_revision


def test_changed_repository_sha_invalidates_bindings() -> None:
    result = acquire_lifecycle_stage(acquisition_request(pr_lineage=(pr_claim(),)))
    changed_sha = "e" * 40

    assert not acquisition_bindings_current(
        result,
        issue_source_revision=ISSUE_REVISION,
        source_revision=changed_sha,
    )

    reacquired = acquire_lifecycle_stage(
        acquisition_request(pr_lineage=(pr_claim(),), source_revision=changed_sha)
    )
    assert reacquired.result_id != result.result_id


def test_pr_state_change_between_reads_changes_the_acquired_stage() -> None:
    draft_read = acquire_lifecycle_stage(
        acquisition_request(pr_lineage=(pr_claim(is_draft=True),))
    )
    merged_read = acquire_lifecycle_stage(
        acquisition_request(pr_lineage=(pr_claim(is_open=False, is_merged=True),))
    )

    assert draft_read.lifecycle_stage is LifecycleStage.DRAFT_PR
    assert merged_read.lifecycle_stage is LifecycleStage.MERGED
    assert draft_read.result_id != merged_read.result_id


def test_partial_api_failure_fails_closed() -> None:
    result = acquire_lifecycle_stage(
        acquisition_request(
            pr_lineage=(pr_claim(),),
            lineage_enumeration=incomplete_enumeration(
                "partial API failure: page 2 of 3 errored"
            ),
        )
    )

    assert result.outcome is LifecycleAcquisitionOutcome.UNAVAILABLE
    assert result.reason_codes == (REASON_INCOMPLETE_ENUMERATION,)


def test_pagination_limit_before_completeness_fails_closed() -> None:
    result = acquire_lifecycle_stage(
        acquisition_request(
            lineage_enumeration=incomplete_enumeration(
                "pagination limit reached before total matched"
            )
        )
    )

    assert result.outcome is LifecycleAcquisitionOutcome.UNAVAILABLE
    assert result.reason_codes == (REASON_INCOMPLETE_ENUMERATION,)


def test_tampered_result_id_is_rejected() -> None:
    result = acquire_lifecycle_stage(acquisition_request(pr_lineage=(pr_claim(),)))

    with pytest.raises(ValueError, match="result_id does not match"):
        LifecycleStageAcquisitionResult(
            repository=result.repository,
            issue_number=result.issue_number,
            issue_source_revision=result.issue_source_revision,
            source_revision=result.source_revision,
            observed_at=result.observed_at,
            outcome=result.outcome,
            lifecycle_stage=result.lifecycle_stage,
            reason_codes=result.reason_codes,
            verified_claims=result.verified_claims,
            result_id="lifecycle-stage-acquisition:" + "0" * 64,
        )


# ---------------------------------------------------------------------------
# Architecture protection
# ---------------------------------------------------------------------------


def test_existing_lifecycle_stage_vocabulary_is_reused() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    enum_definitions = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(
            isinstance(base, ast.Name) and base.id == "Enum"
            for base in node.bases
        )
    ]
    # Only the outcome enum is defined here; LifecycleStage itself is reused.
    assert enum_definitions == ["LifecycleAcquisitionOutcome"]

    imported_names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "LifecycleStage" in imported_names


def test_no_competing_state_model_scheduler_or_authority() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    class_names = [
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ]
    forbidden_fragments = (
        "Scheduler",
        "Queue",
        "Router",
        "Approval",
        "Authorization",
        "OperationalState",
        "Store",
        "Controller",
    )
    for name in class_names:
        assert not any(
            fragment in name for fragment in forbidden_fragments
        ), f"forbidden architecture fragment in class {name}"

    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    for module in imported_modules:
        lowered = module.lower()
        assert "schedul" not in lowered
        assert "workflow" not in lowered


def test_reason_codes_are_bounded_and_documented() -> None:
    assert LIFECYCLE_ACQUISITION_REASON_CODES == frozenset(
        {
            REASON_ACQUIRED,
            REASON_NO_VERIFIED_PR_LINEAGE,
            REASON_INCOMPLETE_ENUMERATION,
            REASON_CONFLICTING_PR_CLAIMS,
            REASON_PR_LINKAGE_UNVERIFIABLE,
            REASON_PR_REPOSITORY_MISMATCH,
            REASON_CLOSED_UNMERGED_PR,
        }
    )


def test_missing_lifecycle_evidence_still_fails_closed_downstream() -> None:
    """The existing reader keeps its named fail-closed reason when no stage
    is acquirable: the acquirer never manufactures a stage to fill the gap."""

    transport = _NullTransport()
    bundle = LiveCandidateEvidence(
        repository=REPOSITORY,
        issue_transport=transport,
        observed_at=OBSERVED_AT,
        source_revision=SOURCE_REVISION,
        lifecycle_stage=None,
        primary_claims=(),
        approval_applicability=None,
        freshness_state=None,
        requested_mode=None,
        environment=None,
        dependency_depth=None,
        substitutable=None,
    )
    reader = LiveCandidateEvidenceReader(bundle)

    outcome = reader.read_candidate_evidence_detailed(REPOSITORY, ISSUE_NUMBER)

    assert outcome.evidence is None
    assert outcome.failure_reason == REASON_MISSING_LIFECYCLE_STAGE


class _NullTransport:
    def get_issue(self, repository: str, issue_number: int):  # pragma: no cover
        raise AssertionError("no live read may happen before the fail-closed check")
