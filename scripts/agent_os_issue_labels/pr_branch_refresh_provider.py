"""Production composition for the governed #1187 PR branch-refresh lifecycle.

This module implements the concrete ``PullRequestBranchRefreshProvider`` seam
without owning refresh admission, scope checks, validation ordering, label
reconciliation, or final branch-current proof. Those semantics remain in
``pr_branch_refresh.refresh_pull_request_branch``.

The provider prepares exactly one rebased candidate head with fixed Git argv and
then delegates the only remote non-fast-forward mutation to #1381
``update_branch_with_expected_head``. The live backing provider reacquires GitHub
PR/base/head/scope evidence and performs only the managed-label operations that
#1187/#1038 authorize. Validation and bounded process execution remain injected
from their existing canonical owners. There is no retry, merge-main fallback,
unconditional force push, protected-branch mutation, credential acquisition, or
alternate refresh path here.
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
    PullRequestBranchRefreshRequest,
    PullRequestBranchRefreshResult,
    PullRequestBranchSnapshot,
    refresh_pull_request_branch,
)
from .pr_reconciler import LivePullRequestSnapshot, PullRequestLabelProvider

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


@runtime_checkable
class PullRequestBranchRefreshBackingProvider(PullRequestLabelProvider, Protocol):
    """Live PR/read/validation capabilities consumed by the concrete provider."""

    def read_branch(self, repository: str, pr_number: int) -> PullRequestBranchSnapshot: ...

    def run_required_validation(
        self,
        repository: str,
        pr_number: int,
        *,
        head_sha: str,
        command_ids: tuple[str, ...],
    ) -> BranchRefreshValidationResult: ...


@runtime_checkable
class BranchRefreshValidationExecutor(Protocol):
    """Existing validation owner used by the live GitHub backing provider."""

    def run_required_validation(
        self,
        repository: str,
        pr_number: int,
        *,
        head_sha: str,
        command_ids: tuple[str, ...],
    ) -> BranchRefreshValidationResult: ...


@runtime_checkable
class BlockingReviewThreadsReader(Protocol):
    """Existing review-evidence owner used only for lifecycle label projection."""

    def blocking_review_threads(self, repository: str, pr_number: int) -> int: ...


@dataclass(slots=True)
class GitHubPullRequestBranchRefreshBackingProvider(PullRequestBranchRefreshBackingProvider):
    """Concrete live GitHub reads/managed-label writes for #1187.

    ``github_client`` is an already-authenticated PyGithub-compatible client. This
    module never acquires credentials. ``validation_executor`` and
    ``review_threads_reader`` are canonical owners supplied by the execution
    surface; this class does not reimplement validation or review-thread logic.

    Read failures are projected into fail-closed evidence using the exact
    request-bound identities: branch state becomes ``unknown``, mergeability
    becomes ``unknown``, labels are unavailable, and review state is blocking.
    That prevents a provider/library exception from turning into mutation
    authority while preserving #1187's own admission and post-write decisions.
    """

    github_client: object
    request: PullRequestBranchRefreshRequest
    validation_executor: BranchRefreshValidationExecutor
    review_threads_reader: BlockingReviewThreadsReader
    _validation_state_by_head: dict[str, str] = field(default_factory=dict, init=False)
    _label_reconciliation_blocked: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not hasattr(self.github_client, "get_repo"):
            raise TypeError("github_client must provide get_repo")
        if not isinstance(self.validation_executor, BranchRefreshValidationExecutor):
            raise TypeError("validation_executor does not satisfy BranchRefreshValidationExecutor")
        if not isinstance(self.review_threads_reader, BlockingReviewThreadsReader):
            raise TypeError("review_threads_reader does not satisfy BlockingReviewThreadsReader")
        if not isinstance(self.request, PullRequestBranchRefreshRequest):
            raise TypeError("request must be exact PullRequestBranchRefreshRequest")

    def read_branch(self, repository: str, pr_number: int) -> PullRequestBranchSnapshot:
        try:
            repo = self.github_client.get_repo(repository)
            pr = repo.get_pull(pr_number)
            base_branch = str(pr.base.ref)
            head_branch = str(pr.head.ref)
            head_sha = _require_sha40(str(pr.head.sha), "head_sha")
            base_sha = _require_sha40(str(repo.get_branch(base_branch).commit.sha), "base_sha")
            current_main_sha = _require_sha40(
                str(repo.get_branch("main").commit.sha), "current_main_sha"
            )
            mergeability = _mergeability(pr)
            comparison = repo.compare(current_main_sha, head_sha)
            comparison_status = str(getattr(comparison, "status", "unknown"))
            if mergeability == "conflicted":
                branch_state = "conflicted"
            elif comparison_status in {"ahead", "identical"}:
                branch_state = "current"
            elif comparison_status in {"behind", "diverged"}:
                branch_state = "behind"
            else:
                branch_state = "unknown"
            changed_paths = tuple(
                sorted({str(item.filename) for item in pr.get_files() if getattr(item, "filename", None)})
            )
            return PullRequestBranchSnapshot(
                repository=repository,
                pr_number=pr_number,
                base_branch=base_branch,
                base_sha=base_sha,
                head_branch=head_branch,
                head_sha=head_sha,
                current_main_sha=current_main_sha,
                branch_state=branch_state,
                mergeability=mergeability,
                changed_paths=changed_paths,
            )
        except Exception:
            return self._unknown_branch(repository, pr_number)

    def read(self, repository: str, pr_number: int) -> LivePullRequestSnapshot:
        branch = self.read_branch(repository, pr_number)
        self._label_reconciliation_blocked = (
            branch.branch_state == "unknown" or branch.mergeability == "unknown"
        )
        try:
            repo = self.github_client.get_repo(repository)
            pr = repo.get_pull(pr_number)
            labels = tuple(sorted({str(item.name) for item in repo.get_issue(pr_number).labels}))
            draft = bool(getattr(pr, "draft", True))
        except Exception:
            self._label_reconciliation_blocked = True
            labels = ()
            draft = True

        try:
            blocking_review_threads = self.review_threads_reader.blocking_review_threads(
                repository, pr_number
            )
            if type(blocking_review_threads) is not int or blocking_review_threads < 0:
                raise ValueError("blocking review-thread count is malformed")
        except Exception:
            self._label_reconciliation_blocked = True
            blocking_review_threads = 1

        validation_state = self._validation_state_by_head.get(branch.head_sha, "pending")
        return LivePullRequestSnapshot(
            repository=repository,
            pr_number=pr_number,
            head_sha=branch.head_sha,
            draft=draft,
            mergeable=branch.mergeability == "mergeable",
            conflicted=branch.mergeability == "conflicted",
            behind=branch.branch_state == "behind",
            validation_state=validation_state,
            blocking_review_threads=blocking_review_threads,
            labels=labels,
        )

    def available_labels(self, repository: str) -> tuple[str, ...]:
        if self._label_reconciliation_blocked:
            return ()
        try:
            repo = self.github_client.get_repo(repository)
            return tuple(sorted({str(item.name) for item in repo.get_labels()}))
        except Exception:
            return ()

    def add_label(self, repository: str, pr_number: int, label: str) -> None:
        self.github_client.get_repo(repository).get_issue(pr_number).add_to_labels(label)

    def remove_label(self, repository: str, pr_number: int, label: str) -> None:
        self.github_client.get_repo(repository).get_issue(pr_number).remove_from_labels(label)

    def run_required_validation(
        self,
        repository: str,
        pr_number: int,
        *,
        head_sha: str,
        command_ids: tuple[str, ...],
    ) -> BranchRefreshValidationResult:
        try:
            result = self.validation_executor.run_required_validation(
                repository,
                pr_number,
                head_sha=head_sha,
                command_ids=command_ids,
            )
        except Exception:
            result = BranchRefreshValidationResult(
                head_sha=head_sha,
                status="failing",
                command_ids=command_ids,
            )
        if result.head_sha == head_sha:
            self._validation_state_by_head[head_sha] = (
                "green" if result.status == "green" else "failing"
            )
        return result

    def _unknown_branch(self, repository: str, pr_number: int) -> PullRequestBranchSnapshot:
        request = self.request
        return PullRequestBranchSnapshot(
            repository=repository,
            pr_number=pr_number,
            base_branch=request.base_branch,
            base_sha=request.expected_base_sha,
            head_branch="unknown",
            head_sha=request.expected_head_sha,
            current_main_sha=request.current_main_sha,
            branch_state="unknown",
            mergeability="unknown",
            changed_paths=(),
        )


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

    def read(self, repository: str, pr_number: int) -> LivePullRequestSnapshot:
        return self.backing.read(repository, pr_number)

    def available_labels(self, repository: str) -> tuple[str, ...]:
        return self.backing.available_labels(repository)

    def add_label(self, repository: str, pr_number: int, label: str) -> None:
        self.backing.add_label(repository, pr_number, label)

    def remove_label(self, repository: str, pr_number: int, label: str) -> None:
        self.backing.remove_label(repository, pr_number, label)

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
        """Prepare one candidate rebase and publish it only through #1381."""

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
            return _blocked(expected_head_sha, blocker)
        if not self.authorization_current or not self.branch_update_authorized:
            return _blocked(expected_head_sha, "authorization.refresh-required-before-preparation")

        merge_base_result = self.runner.run(
            (self.git_binary, "merge-base", expected_head_sha, current_main_sha),
            cwd=self.repository_root,
            env=dict(self.environment),
        )
        merge_base_sha = _exact_head(merge_base_result)
        if merge_base_sha is None:
            return _blocked(expected_head_sha, "merge-base-unavailable")
        if merge_base_sha == current_main_sha:
            return _blocked(expected_head_sha, "branch.refresh-not-required-after-merge-base")

        rebase = self.runner.run(
            (
                self.git_binary,
                "rebase",
                "--no-autostash",
                "--onto",
                current_main_sha,
                merge_base_sha,
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


def run_production_pull_request_branch_refresh(
    *,
    github_client: object,
    runner: BranchUpdateRunner,
    validation_executor: BranchRefreshValidationExecutor,
    review_threads_reader: BlockingReviewThreadsReader,
    request: PullRequestBranchRefreshRequest,
    repository_root: str,
    invocation_id: str,
    environment: Mapping[str, str] | None = None,
    git_binary: str = "git",
) -> PullRequestBranchRefreshResult:
    """Reacquire live GitHub evidence and delegate exactly once to #1187.

    The caller supplies already-established credentialed GitHub, validation,
    review-evidence, and bounded-process capabilities. This function creates no
    alternate authority. Request authorization is passed through unchanged to
    both #1187 and the #1381 branch-update transport.
    """

    if not isinstance(request, PullRequestBranchRefreshRequest):
        raise TypeError("request must be exact PullRequestBranchRefreshRequest")
    backing = GitHubPullRequestBranchRefreshBackingProvider(
        github_client=github_client,
        request=request,
        validation_executor=validation_executor,
        review_threads_reader=review_threads_reader,
    )
    provider = ProductionPullRequestBranchRefreshProvider(
        backing=backing,
        runner=runner,
        repository_root=repository_root,
        invocation_id=invocation_id,
        authorization_id=request.authorization_id,
        authorization_current=request.authorization_current,
        branch_update_authorized=request.branch_refresh_authorized,
        environment=dict(environment or {}),
        git_binary=git_binary,
    )
    return refresh_pull_request_branch(provider, request)


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


def _mergeability(pr: object) -> str:
    mergeable_state = str(getattr(pr, "mergeable_state", "unknown") or "unknown")
    mergeable = getattr(pr, "mergeable", None)
    if mergeable_state == "dirty" or mergeable is False:
        return "conflicted"
    if mergeable is None or mergeable_state == "unknown":
        return "unknown"
    return "mergeable"


def _require_sha40(value: str, name: str) -> str:
    normalized = value.lower()
    if _SHA40_RE.fullmatch(normalized) is None:
        raise ValueError(f"{name} must be a full lowercase commit SHA")
    return normalized


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
