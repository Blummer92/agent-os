from __future__ import annotations

from scripts.agent_os_issue_labels.pr_branch_refresh import (
    BranchRefreshMutationResult,
    PullRequestBranchRefreshRequest,
    PullRequestBranchSnapshot,
    refresh_pull_request_branch,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_operator import _receipt_from_result

REPO = "Blummer92/agent-os"
OLD = "a" * 40
MAIN = "b" * 40
PATH = "scripts/agent_os_issue_labels/pr_branch_refresh.py"


class MutationBoundaryProvider:
    def __init__(self, mutation_status: str = "conflict") -> None:
        self.mutation_status = mutation_status
        self.mutation_calls = 0
        self.snapshot = PullRequestBranchSnapshot(
            repository=REPO,
            pr_number=1363,
            base_branch="main",
            base_sha=MAIN,
            head_branch="agent/1363-refresh",
            head_sha=OLD,
            current_main_sha=MAIN,
            branch_state="behind",
            mergeability="mergeable",
            changed_paths=(PATH,),
        )

    def read_branch(self, repository: str, pr_number: int) -> PullRequestBranchSnapshot:
        return self.snapshot

    def rebase_onto_main(self, repository: str, pr_number: int, **kwargs) -> BranchRefreshMutationResult:
        self.mutation_calls += 1
        return BranchRefreshMutationResult(
            status=self.mutation_status,
            old_head_sha=OLD,
            new_head_sha=None,
            reason_code=f"refresh.{self.mutation_status}",
        )

    def run_required_validation(self, *args, **kwargs):
        raise AssertionError("validation must not run after failed mutation attempt")

    # Label-provider methods are unreachable in these mutation-boundary cases.
    def read(self, repository: str, pr_number: int):
        raise AssertionError("lifecycle read must not run")

    def available_labels(self, repository: str):
        raise AssertionError("label discovery must not run")

    def add_label(self, repository: str, pr_number: int, label: str):
        raise AssertionError("label mutation must not run")

    def remove_label(self, repository: str, pr_number: int, label: str):
        raise AssertionError("label mutation must not run")


def request(**overrides) -> PullRequestBranchRefreshRequest:
    values = dict(
        repository=REPO,
        pr_number=1363,
        base_branch="main",
        expected_base_sha=MAIN,
        expected_head_sha=OLD,
        current_main_sha=MAIN,
        authorization_id="refresh-authorization:test",
        authorization_current=True,
        allowed_changed_paths=(PATH,),
        forbidden_paths=(".github/workflows/x.yml",),
        required_validation_command_ids=("pytest:pr-branch-refresh",),
        branch_refresh_authorized=True,
        label_write_authorized=False,
    )
    values.update(overrides)
    return PullRequestBranchRefreshRequest(**values)


def test_preflight_block_leaves_authorization_unconsumed() -> None:
    provider = MutationBoundaryProvider()
    result = refresh_pull_request_branch(provider, request(authorization_current=False))
    assert provider.mutation_calls == 0
    assert result.side_effects_performed is False
    receipt = _receipt_from_result(
        result=result,
        authorization_id="refresh-authorization:test",
        admitted_main_sha=MAIN,
    )
    assert receipt.authorization_consumed is False
    assert receipt.mutation_count == 0


def test_admitted_failed_mutation_consumes_authorization_exactly_once() -> None:
    provider = MutationBoundaryProvider("conflict")
    result = refresh_pull_request_branch(provider, request())
    assert provider.mutation_calls == 1
    assert result.status == "blocked"
    assert result.side_effects_performed is True
    assert result.automatic_retry_authorized is False

    receipt = _receipt_from_result(
        result=result,
        authorization_id="refresh-authorization:test",
        admitted_main_sha=MAIN,
    )
    assert receipt.authorization_consumed is True
    assert receipt.mutation_count == 1
    assert receipt.new_head_sha is None
    assert receipt.rollback_posture == "restore-old-head-with-separate-authorization"


def test_admitted_ambiguous_mutation_also_consumes_authorization() -> None:
    provider = MutationBoundaryProvider("ambiguous")
    result = refresh_pull_request_branch(provider, request())
    assert provider.mutation_calls == 1
    assert result.status == "manual-review"
    assert result.side_effects_performed is True

    receipt = _receipt_from_result(
        result=result,
        authorization_id="refresh-authorization:test",
        admitted_main_sha=MAIN,
    )
    assert receipt.authorization_consumed is True
    assert receipt.mutation_count == 1
