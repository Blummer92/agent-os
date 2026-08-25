"""Production composition for the governed #1187 PR branch-refresh lifecycle.

This module implements the concrete ``PullRequestBranchRefreshProvider`` seam
without owning refresh admission, scope checks, validation ordering, label
reconciliation, or final branch-current proof.  Those semantics remain in
``pr_branch_refresh.refresh_pull_request_branch``.

The provider prepares exactly one rebased candidate head with fixed Git argv and
then delegates the only remote non-fast-forward mutation to #1381
``update_branch_with_expected_head``.  It performs no retry, merge-main fallback,
unconditional force push, protected-branch mutation, or alternate refresh path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

from scripts.agent_os_github_git_objects import (
    BranchUpdateRunner,
    ExpectedHeadBranchUpdateRequest,
    ExpectedHeadBranchUpdateStatus,
    update_branch_with_expected_head,
)

from .pr_branch_refresh import (
    BranchRefreshMutationResult,
    BranchRefreshValidationResult,
    PullRequestBranchRefreshProvider,
    PullRequestBranchSnapshot,
)
from .pr_reconciler import LivePullRequestSnapshot, PullRequestLabelProvider

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


@runtime_checkable
class PullRequestBranchRefreshBackingProvider(PullRequestLabelProvider, Protocol):
    """Existing live PR/read/validation capabilities composed by this provider."""

    def read_branch(self, repository: str, pr_number: int) -> PullRequestBranchSnapshot: ...

    def run_required_validation(
        self,
        repository: str,
        pr_number: int,
        *,
        head_sha: str,
        command_ids: tuple[str, ...],
    ) -> BranchRefreshValidationResult: ...


@dataclass(slots=True)
class ProductionPullRequestBranchRefreshProvider(PullRequestBranchRefreshProvider):
    """Compose fixed rebase preparation with the existing #1381 CAS transport."""

    backing: PullRequestBranchRefreshBackingProvider
    runner: BranchUpdateRunner
    repository_root: str
    invocation_id: str
    authorization_id: str
    authorization_current: bool
    branch_update_authorized: bool
    environment: Mapping[str, str] = field(default_factory=dict)
    git_binary: str = "git"

    def __post_init__(self) -> None:
        if not isinstance(self.backing, PullRequestBranchRefreshBackingProvider):
            raise TypeError("backing does not satisfy PullRequestBranchRefreshBackingProvider")
        if not isinstance(self.runner, BranchUpdateRunner):
            raise TypeError("runner does not satisfy BranchUpdateRunner")
        if not isinstance(self.repository_root, str) or not self.repository_root:
            raise ValueError("repository_root is required")
        if not isinstance(self.git_binary, str) or not self.git_binary or "\x00" in self.git_binary:
            raise ValueError("git_binary is malformed")
        for name in ("invocation_id", "authorization_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} is required")
        if type(self.authorization_current) is not bool:
            raise TypeError("authorization_current must be bool")
        if type(self.branch_update_authorized) is not bool:
            raise TypeError("branch_update_authorized must be bool")

    # PullRequestLabelProvider delegation.  Label lifecycle remains #1187-owned.
    def read(self, repository: str, pr_number: int) -> LivePullRequestSnapshot:
        return self.backing.read(repository, pr_number)

    def available_labels(self, repository: str) -> tuple[str, ...]:
        return self.backing.available_labels(repository)

    def add_label(self, repository: str, pr_number: int, label: str) -> None:
        self.backing.add_label(repository, pr_number, label)

    def remove_label(self, repository: str, pr_number: int, label: str) -> None:
        self.backing.remove_label(repository, pr_number, label)

    # #1187 read/validation delegation.
    def read_branch(self, repository: str, pr_number: int) -> PullRequestBranchSnapshot:
        return self.backing.read_branch(repository, pr_number)

    def run_required_validation(
        self,
        repository: str,
        pr_number: int,
        *,
        head_sha: str,
        command_ids: tuple[str, ...],
    ) -> BranchRefreshValidationResult:
        return self.backing.run_required_validation(
            repository,
            pr_number,
            head_sha=head_sha,
            command_ids=command_ids,
        )

    def rebase_onto_main(
        self,
        repository: str,
        pr_number: int,
        *,
        expected_head_sha: str,
        expected_base_sha: str,
        current_main_sha: str,
    ) -> BranchRefreshMutationResult:
        """Prepare one candidate rebase and publish it only through #1381.

        ``refresh_pull_request_branch`` has already performed canonical admission.
        This method still reacquires the live branch immediately before local
        preparation so a moved head/base/main fails before any remote mutation.
        The fixed rebase operates on commit identities, not caller-supplied flags
        or shell text.  A failed/ambiguous local preparation is never retried.
        """

        snapshot = self.backing.read_branch(repository, pr_number)
        blocker = _preparation_blocker(
            snapshot,
            repository=repository,
            pr_number=pr_number,
            expected_head_sha=expected_head_sha,
            expected_base_sha=expected_base_sha,
            current_main_sha=current_main_sha,
        )
        if blocker is not None:
            return BranchRefreshMutationResult(
                status="blocked",
                old_head_sha=expected_head_sha,
                reason_code=blocker,
            )

        rebase = self.runner.run(
            (
                self.git_binary,
                "rebase",
                "--no-autostash",
                "--onto",
                current_main_sha,
                expected_base_sha,
                expected_head_sha,
            ),
            cwd=self.repository_root,
            env=dict(self.environment),
        )
        if not rebase.started:
            return _blocked(expected_head_sha, "rebase-not-started")
        if rebase.timed_out or not rebase.termination_confirmed:
            return _ambiguous(expected_head_sha, "rebase-outcome-uncertain")
        if rebase.return_code != 0:
            return _blocked(expected_head_sha, "rebase-rejected")

        head = self.runner.run(
            (self.git_binary, "rev-parse", "--verify", "HEAD^{commit}"),
            cwd=self.repository_root,
            env=dict(self.environment),
        )
        proposed_head_sha = _exact_head(head)
        if proposed_head_sha is None:
            return _blocked(expected_head_sha, "rebased-head-unavailable")
        if proposed_head_sha == expected_head_sha:
            return _blocked(expected_head_sha, "rebased-head-unchanged")

        update = update_branch_with_expected_head(
            ExpectedHeadBranchUpdateRequest(
                repository=repository,
                branch=snapshot.head_branch,
                expected_head_sha=expected_head_sha,
                proposed_head_sha=proposed_head_sha,
                admitted_main_sha=current_main_sha,
                invocation_id=self.invocation_id,
                authorization_id=self.authorization_id,
                authorization_current=self.authorization_current,
                branch_update_authorized=self.branch_update_authorized,
            ),
            self.runner,
            repository_root=self.repository_root,
            environment=dict(self.environment),
            git_binary=self.git_binary,
        )
        if update.status is ExpectedHeadBranchUpdateStatus.CONFIRMED:
            return BranchRefreshMutationResult(
                status="updated",
                old_head_sha=expected_head_sha,
                new_head_sha=proposed_head_sha,
                reason_code=update.reason,
            )
        if update.status is ExpectedHeadBranchUpdateStatus.UNCERTAIN:
            return _ambiguous(expected_head_sha, f"transport.{update.reason}")
        return _blocked(expected_head_sha, f"transport.{update.reason}")


def _preparation_blocker(
    snapshot: PullRequestBranchSnapshot,
    *,
    repository: str,
    pr_number: int,
    expected_head_sha: str,
    expected_base_sha: str,
    current_main_sha: str,
) -> str | None:
    if snapshot.repository != repository or snapshot.pr_number != pr_number:
        return "identity.mismatch-before-preparation"
    if snapshot.head_sha != expected_head_sha:
        return "head.moved-before-preparation"
    if snapshot.base_sha != expected_base_sha or snapshot.current_main_sha != current_main_sha:
        return "base.moved-before-preparation"
    if snapshot.branch_state != "behind" or snapshot.mergeability in {"conflicted", "unknown"}:
        return "branch.refresh-not-eligible-before-preparation"
    return None


def _exact_head(observation: object) -> str | None:
    if (
        not hasattr(observation, "succeeded")
        or not bool(getattr(observation, "succeeded"))
        or not isinstance(getattr(observation, "stdout", None), str)
    ):
        return None
    lines = [line.strip() for line in observation.stdout.splitlines() if line.strip()]
    if len(lines) != 1 or _SHA40_RE.fullmatch(lines[0]) is None:
        return None
    return lines[0]


def _blocked(old_head_sha: str, reason: str) -> BranchRefreshMutationResult:
    return BranchRefreshMutationResult(
        status="blocked",
        old_head_sha=old_head_sha,
        reason_code=reason,
    )


def _ambiguous(old_head_sha: str, reason: str) -> BranchRefreshMutationResult:
    return BranchRefreshMutationResult(
        status="ambiguous",
        old_head_sha=old_head_sha,
        reason_code=reason,
    )
