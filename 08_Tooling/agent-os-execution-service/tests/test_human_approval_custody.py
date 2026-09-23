from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from agent_os_execution_service.execution_authorization_source import (
    ExecutionAuthorizationCommentSnapshot,
    ExecutionAuthorizationSourceSnapshot,
)
from agent_os_execution_service import human_approval_custody as module
from scripts.agent_os_issue_acceptance.approval_records import ApprovalState

REPOSITORY = "Blummer92/agent-os"
ISSUE = 1982
PROVENANCE = "pre-publication-evidence:" + "a" * 64
OWNER = "Blummer92"


class Transport:
    def __init__(self, comments, *, complete=True, owner=OWNER):
        self.snapshot = ExecutionAuthorizationSourceSnapshot(
            repository=REPOSITORY,
            issue_number=ISSUE,
            owner_login=owner,
            owner_type="User",
            comments_complete=complete,
            comments=tuple(comments),
        )

    def read_authorization_source(self, repository, issue_number):
        assert (repository, issue_number) == (REPOSITORY, ISSUE)
        return self.snapshot


def comment(comment_id, body, *, author=OWNER, created_at="2026-09-11T21:40:00Z"):
    return ExecutionAuthorizationCommentSnapshot(
        comment_id=comment_id,
        author_login=author,
        created_at=created_at,
        body=body,
    )


def test_exact_owner_approval_command_becomes_typed_decision_only() -> None:
    result = module.reacquire_human_approval_decision(
        transport=Transport([comment(10, f"/agent-os approve-candidate {PROVENANCE}")]),
        repository=REPOSITORY,
        issue_number=ISSUE,
        candidate_provenance_id=PROVENANCE,
    )
    assert result.candidate_provenance_id == PROVENANCE
    assert result.source_comment_id == 10
    assert result.authorizer_id == OWNER
    assert result.approval_decision.state is ApprovalState.APPROVED
    assert result.approval_decision.decision_id == "github-comment:10"
    assert result.approval_decision.decision_at == "2026-09-11T21:40:00Z"
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


@pytest.mark.parametrize(
    "body",
    [
        "approved",
        f"/agent-os approve-candidate {PROVENANCE} --force",
        f"/agent-os approve-candidate {PROVENANCE}\nextra",
        "/agent-os approve-candidate pre-publication-evidence:bad",
    ],
)
def test_prose_extra_tokens_and_wrong_identity_do_not_approve(body: str) -> None:
    with pytest.raises(module.HumanApprovalCustodyError, match="human-approval-missing"):
        module.reacquire_human_approval_decision(
            transport=Transport([comment(10, body)]),
            repository=REPOSITORY,
            issue_number=ISSUE,
            candidate_provenance_id=PROVENANCE,
        )


def test_non_owner_and_incomplete_comment_source_fail_closed() -> None:
    with pytest.raises(module.HumanApprovalCustodyError, match="human-approval-missing"):
        module.reacquire_human_approval_decision(
            transport=Transport([
                comment(10, f"/agent-os approve-candidate {PROVENANCE}", author="mallory")
            ]),
            repository=REPOSITORY,
            issue_number=ISSUE,
            candidate_provenance_id=PROVENANCE,
        )
    with pytest.raises(module.HumanApprovalCustodyError, match="not-complete"):
        module.reacquire_human_approval_decision(
            transport=Transport([], complete=False),
            repository=REPOSITORY,
            issue_number=ISSUE,
            candidate_provenance_id=PROVENANCE,
        )


def test_duplicate_comment_identity_is_ambiguous() -> None:
    body = f"/agent-os approve-candidate {PROVENANCE}"
    with pytest.raises(module.HumanApprovalCustodyError, match="ambiguous"):
        module.reacquire_human_approval_decision(
            transport=Transport([comment(10, body), comment(10, body)]),
            repository=REPOSITORY,
            issue_number=ISSUE,
            candidate_provenance_id=PROVENANCE,
        )


def test_production_composition_reuses_existing_candidate_and_custody_owners() -> None:
    source = inspect.getsource(module.produce_human_approval_custody)
    assert "load_candidate_approval_provenance(" in source
    assert "prepare_candidate_packet(" in source
    assert "CandidatePacketPhase.EXECUTION_CANDIDATE" in source
    assert "build_approval_custody_evidence(" in source
    assert "append_pre_publication_evidence(" in source
    assert "candidate-provenance-drift" in source
    assert "self-approval-forbidden" in source


def test_module_has_no_second_authority_or_external_execution_surface() -> None:
    source = inspect.getsource(module)
    for forbidden in (
        "subprocess",
        "requests.",
        "google.cloud",
        "Scheduler(",
        "execution_authorized=True",
        "merge_authorized=True",
        "ApprovalRecord(",
    ):
        assert forbidden not in source
