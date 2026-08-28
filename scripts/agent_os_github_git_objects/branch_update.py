"""Expected-head-bound non-fast-forward update for one non-protected branch.

This is a specialized publication primitive for GH-LIFE4A / #1381.
It does not expose arbitrary Git commands, refspecs, force flags, retries,
merge behavior, lifecycle authority, or protected-branch mutation.

The caller supplies a bounded runner.  The only mutation argv constructed by
this module is an exact ``git push --force-with-lease=<ref>:<old>`` for the
validated branch, expected old head, and proposed new head.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, runtime_checkable

from .models import (
    ExpectedHeadBranchUpdateRequest,
    ExpectedHeadBranchUpdateResult,
    ExpectedHeadBranchUpdateStatus,
    MutationState,
    require_branch,
    require_repository,
    require_sha40,
)


@dataclass(frozen=True, slots=True)
class BranchUpdateObservation:
    started: bool
    return_code: int | None
    timed_out: bool
    termination_confirmed: bool
    stdout: str = ""
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return bool(
            self.started
            and self.termination_confirmed
            and not self.timed_out
            and self.return_code == 0
        )


@runtime_checkable
class BranchUpdateRunner(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: str,
        env: Mapping[str, str],
    ) -> BranchUpdateObservation: ...


def update_branch_with_expected_head(
    request: ExpectedHeadBranchUpdateRequest,
    runner: BranchUpdateRunner,
    *,
    repository_root: str,
    environment: Mapping[str, str] | None = None,
    git_binary: str = "git",
) -> ExpectedHeadBranchUpdateResult:
    """Perform at most one expected-head-bound non-fast-forward update."""

    if not isinstance(request, ExpectedHeadBranchUpdateRequest):
        raise TypeError("request must be ExpectedHeadBranchUpdateRequest")
    if not isinstance(runner, BranchUpdateRunner):
        raise TypeError("runner does not satisfy BranchUpdateRunner")
    if not isinstance(repository_root, str) or not repository_root:
        raise ValueError("repository_root is required")
    if not isinstance(git_binary, str) or not git_binary or "\x00" in git_binary:
        raise ValueError("git_binary is malformed")

    repository = require_repository(request.repository)
    branch = require_branch(request.branch)
    expected = require_sha40(request.expected_head_sha, "expected_head_sha")
    proposed = require_sha40(request.proposed_head_sha, "proposed_head_sha")
    require_sha40(request.admitted_main_sha, "admitted_main_sha")

    if not request.branch_update_authorized or not request.authorization_current:
        return _result(
            request,
            ExpectedHeadBranchUpdateStatus.BLOCKED,
            "authorization-required",
            mutation_state=MutationState.NOT_ATTEMPTED,
        )

    env = dict(environment or {})

    remote_ref = f"refs/heads/{branch}"

    before = runner.run(
        (git_binary, "ls-remote", "--heads", "origin", remote_ref),
        cwd=repository_root,
        env=env,
    )
    observed_before = _parse_exact_remote_head(before, remote_ref)
    if observed_before is None:
        return _result(
            request,
            ExpectedHeadBranchUpdateStatus.BLOCKED,
            "remote-head-unavailable",
            mutation_state=MutationState.NOT_ATTEMPTED,
        )
    if observed_before != expected:
        return _result(
            request,
            ExpectedHeadBranchUpdateStatus.BLOCKED,
            "expected-head-mismatch",
            observed_before=observed_before,
            mutation_state=MutationState.NOT_ATTEMPTED,
        )

    push = runner.run(
        (
            git_binary,
            "push",
            f"--force-with-lease={remote_ref}:{expected}",
            "origin",
            f"{proposed}:{remote_ref}",
        ),
        cwd=repository_root,
        env=env,
    )

    if not push.started:
        return _result(
            request,
            ExpectedHeadBranchUpdateStatus.BLOCKED,
            "push-not-started",
            observed_before=observed_before,
            mutation_attempted=False,
            mutation_state=MutationState.FAILED_BEFORE_SIDE_EFFECT,
        )

    if (
        push.timed_out
        or not push.termination_confirmed
    ):
        return _result(
            request,
            ExpectedHeadBranchUpdateStatus.UNCERTAIN,
            "push-outcome-uncertain",
            observed_before=observed_before,
            mutation_attempted=True,
            mutation_state=MutationState.UNCERTAIN,
        )

    if push.return_code != 0:
        return _result(
            request,
            ExpectedHeadBranchUpdateStatus.BLOCKED,
            "push-rejected",
            observed_before=observed_before,
            mutation_attempted=True,
            mutation_state=MutationState.FAILED_BEFORE_SIDE_EFFECT,
        )

    after = runner.run(
        (git_binary, "ls-remote", "--heads", "origin", remote_ref),
        cwd=repository_root,
        env=env,
    )
    observed_after = _parse_exact_remote_head(after, remote_ref)
    if observed_after != proposed:
        return _result(
            request,
            ExpectedHeadBranchUpdateStatus.UNCERTAIN,
            "post-update-mismatch",
            observed_before=observed_before,
            observed_after=observed_after,
            mutation_attempted=True,
            mutation_state=MutationState.UNCERTAIN,
        )

    return _result(
        request,
        ExpectedHeadBranchUpdateStatus.CONFIRMED,
        "branch-updated",
        observed_before=observed_before,
        observed_after=observed_after,
        mutation_attempted=True,
        mutation_state=MutationState.CONFIRMED,
    )


def _parse_exact_remote_head(
    observation: BranchUpdateObservation,
    expected_ref: str,
) -> str | None:
    if not isinstance(observation, BranchUpdateObservation) or not observation.succeeded:
        return None
    lines = [line for line in observation.stdout.splitlines() if line]
    if len(lines) != 1:
        return None
    fields = lines[0].split("\t")
    if len(fields) != 2 or fields[1] != expected_ref:
        return None
    try:
        return require_sha40(fields[0], "remote_head_sha")
    except ValueError:
        return None


def _result(
    request: ExpectedHeadBranchUpdateRequest,
    status: ExpectedHeadBranchUpdateStatus,
    reason: str,
    *,
    observed_before: str | None = None,
    observed_after: str | None = None,
    mutation_attempted: bool = False,
    mutation_state: MutationState,
) -> ExpectedHeadBranchUpdateResult:
    return ExpectedHeadBranchUpdateResult(
        repository=request.repository,
        branch=request.branch,
        expected_head_sha=request.expected_head_sha,
        proposed_head_sha=request.proposed_head_sha,
        admitted_main_sha=request.admitted_main_sha,
        invocation_id=request.invocation_id,
        authorization_id=request.authorization_id,
        status=status,
        reason=reason,
        observed_head_before=observed_before,
        observed_head_after=observed_after,
        mutation_attempted=mutation_attempted,
        mutation_state=mutation_state,
    )
