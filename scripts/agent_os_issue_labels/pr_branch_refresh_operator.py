"""Bounded operator adapters for governed #1187 PR branch refresh.

This module does not grant refresh authority and does not own the #1187
lifecycle. It supplies concrete execution capabilities to the already-canonical
production composition in pr_branch_refresh_provider.py.

No shell strings, arbitrary refspecs, retry loops, or fallback transports are
accepted here.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Mapping

from scripts.agent_os_github_git_objects.branch_update import (
    BranchUpdateObservation,
)
from scripts.agent_os_github_issue_provider.auth import build_token_client


@dataclass(frozen=True, slots=True)
class SubprocessBranchUpdateRunner:
    """Execute caller-supplied fixed argv once with bounded runtime."""

    timeout_seconds: int = 300

    def __post_init__(self) -> None:
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 3600:
            raise ValueError("timeout_seconds must be an int from 1 to 3600")

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: str,
        env: Mapping[str, str],
    ) -> BranchUpdateObservation:
        if (
            type(argv) is not tuple
            or not argv
            or any(not isinstance(item, str) or not item or "\x00" in item for item in argv)
        ):
            raise ValueError("argv must be a non-empty tuple of bounded strings")
        if not isinstance(cwd, str) or not cwd or "\x00" in cwd:
            raise ValueError("cwd is required")
        if not isinstance(env, Mapping):
            raise TypeError("env must be a mapping")

        try:
            completed = subprocess.run(
                list(argv),
                cwd=cwd,
                env=dict(env),
                shell=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            return BranchUpdateObservation(
                started=True,
                return_code=None,
                timed_out=True,
                termination_confirmed=False,
                stdout=_output(error.stdout),
                stderr=_output(error.stderr),
            )
        except OSError as error:
            return BranchUpdateObservation(
                started=False,
                return_code=None,
                timed_out=False,
                termination_confirmed=True,
                stderr=f"{type(error).__name__}:{error}",
            )

        return BranchUpdateObservation(
            started=True,
            return_code=completed.returncode,
            timed_out=False,
            termination_confirmed=True,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def _output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


@dataclass(frozen=True, slots=True)
class PyGithubBlockingReviewThreadsReader:
    """Read current review-thread state through GitHub GraphQL and normalize it."""

    github_client: object

    def __post_init__(self) -> None:
        if not hasattr(self.github_client, "requester"):
            raise TypeError("github_client must expose the canonical PyGithub requester")

    def blocking_review_threads(self, repository: str, pr_number: int) -> int:
        from scripts.agent_os_pr_remediation.normalization import normalize_review_threads

        if (
            not isinstance(repository, str)
            or repository.count("/") != 1
            or not all(repository.split("/"))
        ):
            raise ValueError("repository must be owner/name")
        if type(pr_number) is not int or pr_number <= 0:
            raise ValueError("pr_number must be a positive int")

        owner, name = repository.split("/", 1)
        query = """
        query($owner:String!, $name:String!, $number:Int!) {
          repository(owner:$owner, name:$name) {
            pullRequest(number:$number) {
              reviewThreads(first:100) {
                pageInfo { hasNextPage }
                nodes {
                  id
                  isResolved
                  isOutdated
                  path
                  line
                  originalLine
                  diffSide
                  startLine
                  startDiffSide
                  comments(first:100) {
                    pageInfo { hasNextPage }
                    nodes {
                      databaseId
                      id
                      body
                      createdAt
                      updatedAt
                      author { login }
                    }
                  }
                }
              }
            }
          }
        }
        """

        headers, payload = self.github_client.requester.requestJsonAndCheck(
            "POST",
            "/graphql",
            input={
                "query": query,
                "variables": {
                    "owner": owner,
                    "name": name,
                    "number": pr_number,
                },
            },
        )
        del headers

        threads = (
            payload.get("data", {})
            .get("repository", {})
            .get("pullRequest", {})
            .get("reviewThreads")
        )
        if not isinstance(threads, dict):
            raise RuntimeError("review-thread evidence unavailable")
        page_info = threads.get("pageInfo")
        nodes = threads.get("nodes")
        if not isinstance(page_info, dict) or page_info.get("hasNextPage") is not False:
            raise RuntimeError("review-thread evidence incomplete")
        if not isinstance(nodes, list):
            raise RuntimeError("review-thread evidence malformed")

        raw: list[dict[str, object]] = []
        for thread in nodes:
            if not isinstance(thread, dict):
                raise RuntimeError("review-thread evidence malformed")
            comments = thread.get("comments")
            if not isinstance(comments, dict):
                raise RuntimeError("review-thread comments unavailable")
            comments_page = comments.get("pageInfo")
            comment_nodes = comments.get("nodes")
            if (
                not isinstance(comments_page, dict)
                or comments_page.get("hasNextPage") is not False
                or not isinstance(comment_nodes, list)
                or not comment_nodes
            ):
                raise RuntimeError("review-thread comments incomplete")

            top = comment_nodes[0]
            if not isinstance(top, dict):
                raise RuntimeError("review-thread comment malformed")
            author = top.get("author")
            if not isinstance(author, dict) or not isinstance(author.get("login"), str):
                raise RuntimeError("review-thread reviewer unavailable")
            body = top.get("body")
            if not isinstance(body, str):
                raise RuntimeError("review-thread body unavailable")

            raw.append(
                {
                    "thread_id": thread.get("id"),
                    "top_level_comment_id": top.get("databaseId"),
                    "reviewer": author["login"],
                    "body": body,
                    "resolved": thread.get("isResolved"),
                    "outdated": thread.get("isOutdated"),
                    "superseded": False,
                    "path": thread.get("path"),
                    "line": thread.get("line"),
                    "original_line": thread.get("originalLine"),
                    "side": thread.get("diffSide"),
                    "start_line": thread.get("startLine"),
                    "start_side": thread.get("startDiffSide"),
                    "created_at": top.get("createdAt"),
                    "updated_at": top.get("updatedAt"),
                    "reply_ids": [
                        item.get("id")
                        for item in comment_nodes[1:]
                        if isinstance(item, dict) and isinstance(item.get("id"), str)
                    ],
                    "supersession_evidence": [],
                }
            )

        normalized = normalize_review_threads(raw)
        if any(item.classification == "unavailable" for item in normalized):
            raise RuntimeError("review-thread evidence cannot prove currentness")
        return sum(item.classification == "current-unresolved" for item in normalized)


_REFRESH_VALIDATION_COMMANDS: dict[str, tuple[str, ...]] = {
    "pytest:pr-branch-refresh": (
        ".venv/bin/python",
        "-m",
        "pytest",
        "tests/agent_os_issue_labels/test_pr_branch_refresh.py",
        "-q",
    ),
    "pytest:pr-branch-refresh-provider": (
        ".venv/bin/python",
        "-m",
        "pytest",
        "tests/agent_os_issue_labels/test_pr_branch_refresh_provider.py",
        "-q",
    ),
    "pytest:branch-update": (
        ".venv/bin/python",
        "-m",
        "pytest",
        "tests/agent_os_github_git_objects/test_branch_update.py",
        "-q",
    ),
    "pytest:pr-lifecycle": (
        ".venv/bin/python",
        "-m",
        "pytest",
        "tests/agent_os_issue_labels/test_pr_lifecycle.py",
        "-q",
    ),
    "structure": (
        "bash",
        "07_Agent_Tests/validate-repo-structure.sh",
    ),
}

_CANONICAL_REFRESH_VALIDATION_COMMAND_IDS = tuple(_REFRESH_VALIDATION_COMMANDS)


@dataclass(frozen=True, slots=True)
class ClosedBranchRefreshValidationExecutor:
    """Execute only the closed #1365 validation profile."""

    runner: SubprocessBranchUpdateRunner
    repository_root: str

    def run_required_validation(
        self,
        repository: str,
        pr_number: int,
        *,
        head_sha: str,
        command_ids: tuple[str, ...],
    ):
        from scripts.agent_os_issue_labels.pr_branch_refresh import (
            BranchRefreshValidationResult,
        )

        if type(command_ids) is not tuple or not command_ids:
            raise ValueError("command_ids must be a non-empty tuple")
        if len(set(command_ids)) != len(command_ids):
            raise ValueError("duplicate validation command IDs are not allowed")
        unknown = tuple(item for item in command_ids if item not in _REFRESH_VALIDATION_COMMANDS)
        if unknown:
            return BranchRefreshValidationResult(
                head_sha=head_sha,
                status="failing",
                command_ids=command_ids,
            )

        head = self.runner.run(
            ("git", "rev-parse", "HEAD"),
            cwd=self.repository_root,
            env={},
        )
        if not head.succeeded or head.stdout.strip() != head_sha:
            return BranchRefreshValidationResult(
                head_sha=head_sha,
                status="failing",
                command_ids=command_ids,
            )

        for command_id in command_ids:
            result = self.runner.run(
                _REFRESH_VALIDATION_COMMANDS[command_id],
                cwd=self.repository_root,
                env={},
            )
            if not result.succeeded:
                return BranchRefreshValidationResult(
                    head_sha=head_sha,
                    status="failing",
                    command_ids=command_ids,
                )

        final_head = self.runner.run(
            ("git", "rev-parse", "HEAD"),
            cwd=self.repository_root,
            env={},
        )
        status = (
            "green"
            if final_head.succeeded and final_head.stdout.strip() == head_sha
            else "failing"
        )
        return BranchRefreshValidationResult(
            head_sha=head_sha,
            status=status,
            command_ids=command_ids,
        )


@dataclass(frozen=True, slots=True)
class BranchRefreshOperatorPreflight:
    repository: str
    pr_number: int
    expected_head_sha: str
    current_main_sha: str
    authorization_id: str
    ready: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PullRequestBranchRefreshReceipt:
    """Bounded operator-facing projection of one governed refresh attempt."""

    repository: str
    pr_number: int
    status: str
    authorization_id: str
    authorization_consumed: bool
    admitted_main_sha: str
    old_head_sha: str
    new_head_sha: str | None
    mutation_count: int
    validation_status: str | None
    validation_head_sha: str | None
    lifecycle_reconciliation_status: str | None
    final_current_proven: bool
    blockers: tuple[str, ...]
    reason_codes: tuple[str, ...]
    rollback_posture: str
    side_effects_performed: bool
    ready_for_review_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)
    workflow_authorized: bool = field(default=False, init=False)
    repository_setting_authorized: bool = field(default=False, init=False)
    production_authorized: bool = field(default=False, init=False)
    credential_authorized: bool = field(default=False, init=False)
    external_system_write_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.mutation_count not in {0, 1}:
            raise ValueError("mutation_count must be 0 or 1")
        if self.authorization_consumed != (self.mutation_count == 1):
            raise ValueError("authorization consumption must match mutation-attempt evidence")
        if self.side_effects_performed and not self.authorization_consumed:
            raise ValueError("branch side effects require consumed refresh authorization")


def build_branch_refresh_github_client(environment: Mapping[str, str]):
    """Build the branch-refresh client through the canonical token boundary."""
    return build_token_client(environment, user_agent="agent-os-pr-branch-refresh/1")


def preflight_production_branch_refresh(
    *,
    github_client: object,
    request: object,
    repository_root: str,
) -> BranchRefreshOperatorPreflight:
    """Reacquire bounded live evidence without invoking #1187 or mutating refs."""

    from scripts.agent_os_issue_labels.pr_branch_refresh import PullRequestBranchRefreshRequest
    from scripts.agent_os_issue_labels.pr_branch_refresh_provider import (
        GitHubPullRequestBranchRefreshBackingProvider,
    )

    if not isinstance(request, PullRequestBranchRefreshRequest):
        raise TypeError("request must be exact PullRequestBranchRefreshRequest")
    if not isinstance(repository_root, str) or not repository_root:
        raise ValueError("repository_root is required")

    class _NoValidation:
        def run_required_validation(self, *args, **kwargs):
            raise AssertionError("preflight must not execute validation")

    class _NoReview:
        def blocking_review_threads(self, *args, **kwargs):
            raise AssertionError("preflight must not read review threads")

    backing = GitHubPullRequestBranchRefreshBackingProvider(
        github_client=github_client,
        request=request,
        validation_executor=_NoValidation(),
        review_threads_reader=_NoReview(),
    )
    snapshot = backing.read_branch(request.repository, request.pr_number)

    reasons: list[str] = []
    if not request.authorization_current or not request.branch_refresh_authorized:
        reasons.append("authorization.refresh-required")
    if snapshot.repository != request.repository or snapshot.pr_number != request.pr_number:
        reasons.append("identity.mismatch")
    if snapshot.head_sha != request.expected_head_sha:
        reasons.append("head.moved")
    if (
        snapshot.base_sha != request.expected_base_sha
        or snapshot.current_main_sha != request.current_main_sha
    ):
        reasons.append("base.moved")
    if snapshot.base_branch != request.base_branch:
        reasons.append("base.branch-mismatch")
    if snapshot.branch_state != "behind":
        reasons.append("branch.refresh-not-required-or-unknown")
    # GitHub's conflicted flag is a routing hint for deterministic reconciliation,
    # not a preflight veto. The provider must still prove a conflict-free candidate
    # before the one #1381 mutation attempt. Unknown mergeability remains blocked.
    if snapshot.mergeability == "unknown":
        reasons.append("branch.mergeability-unknown")

    changed = set(snapshot.changed_paths)
    allowed = set(request.allowed_changed_paths)
    forbidden = set(request.forbidden_paths)
    if changed & forbidden:
        reasons.append("scope.forbidden-path")
    if not changed.issubset(allowed):
        reasons.append("scope.expanded")

    return BranchRefreshOperatorPreflight(
        repository=request.repository,
        pr_number=request.pr_number,
        expected_head_sha=request.expected_head_sha,
        current_main_sha=request.current_main_sha,
        authorization_id=request.authorization_id,
        ready=not reasons,
        reason_codes=tuple(reasons),
    )


def refresh_pr(
    *,
    repository: str,
    pr_number: int,
    authorization: object,
    github_client: object,
    repository_root: str,
    invocation_id: str,
    environment: Mapping[str, str],
) -> PullRequestBranchRefreshReceipt:
    """Compose the existing #1187 planner with concrete bounded operators."""

    from scripts.agent_os_issue_labels.pr_branch_refresh import (
        BranchRefreshResult,
        BranchRefreshStatus,
        PullRequestBranchRefreshRequest,
        execute_branch_refresh,
        prepare_branch_refresh,
    )
    from scripts.agent_os_issue_labels.pr_branch_refresh_provider import (
        GitHubPullRequestBranchRefreshBackingProvider,
    )

    if not isinstance(repository, str) or not repository:
        raise ValueError("repository is required")
    if type(pr_number) is not int or pr_number <= 0:
        raise ValueError("pr_number must be positive int")
    if not isinstance(repository_root, str) or not repository_root:
        raise ValueError("repository_root is required")
    if not isinstance(invocation_id, str) or not invocation_id:
        raise ValueError("invocation_id is required")

    auth_repository = getattr(authorization, "repository", None)
    auth_pr = getattr(authorization, "pr_number", None)
    auth_head = getattr(authorization, "expected_head_sha", None)
    auth_base = getattr(authorization, "expected_base_sha", None)
    auth_main = getattr(authorization, "current_main_sha", None)
    auth_base_branch = getattr(authorization, "base_branch", None)
    auth_allowed = getattr(authorization, "allowed_changed_paths", None)
    auth_forbidden = getattr(authorization, "forbidden_paths", None)
    auth_current = getattr(authorization, "authorization_current", None)
    auth_granted = getattr(authorization, "branch_refresh_authorized", None)
    auth_id = getattr(authorization, "authorization_id", None)
    if (
        auth_repository != repository
        or auth_pr != pr_number
        or not isinstance(auth_head, str)
        or not isinstance(auth_base, str)
        or not isinstance(auth_main, str)
        or not isinstance(auth_base_branch, str)
        or not isinstance(auth_allowed, tuple)
        or not isinstance(auth_forbidden, tuple)
        or type(auth_current) is not bool
        or type(auth_granted) is not bool
        or not isinstance(auth_id, str)
    ):
        raise RuntimeError("branch refresh authorization is missing or identity-mismatched")

    request = PullRequestBranchRefreshRequest(
        repository=repository,
        pr_number=pr_number,
        expected_head_sha=auth_head,
        expected_base_sha=auth_base,
        current_main_sha=auth_main,
        base_branch=auth_base_branch,
        allowed_changed_paths=auth_allowed,
        forbidden_paths=auth_forbidden,
        authorization_current=auth_current,
        branch_refresh_authorized=auth_granted,
        authorization_id=auth_id,
    )
    backing = GitHubPullRequestBranchRefreshBackingProvider(
        github_client=github_client,
        request=request,
        validation_executor=ClosedBranchRefreshValidationExecutor(
            runner=SubprocessBranchUpdateRunner(),
            repository_root=repository_root,
        ),
        review_threads_reader=PyGithubBlockingReviewThreadsReader(github_client),
    )
    plan, initial = prepare_branch_refresh(request, backing)
    if plan is None:
        return _receipt_from_result(
            request=request,
            result=initial,
            old_head_sha=request.expected_head_sha,
        )

    confirmation = _confirmation_for_plan(
        plan=plan,
        request=request,
        invocation_id=invocation_id,
        environment=environment,
    )
    result = execute_branch_refresh(plan, confirmation, backing)
    return _receipt_from_result(
        request=request,
        result=result,
        old_head_sha=request.expected_head_sha,
    )


def _confirmation_for_plan(*, plan, request, invocation_id: str, environment: Mapping[str, str]):
    from scripts.agent_os_issue_labels.pr_branch_refresh import BranchRefreshConfirmation

    if environment.get("AGENT_OS_BRANCH_REFRESH_CONFIRM") != "1":
        return BranchRefreshConfirmation(
            plan_id=plan.plan_id,
            operation_fingerprint=plan.operation_fingerprint,
            repository=request.repository,
            pr_number=request.pr_number,
            expected_head_sha=request.expected_head_sha,
            expected_base_sha=request.expected_base_sha,
            current_main_sha=request.current_main_sha,
            authorization_id=request.authorization_id,
            invocation_id=invocation_id,
            confirmed=False,
        )
    return BranchRefreshConfirmation(
        plan_id=plan.plan_id,
        operation_fingerprint=plan.operation_fingerprint,
        repository=request.repository,
        pr_number=request.pr_number,
        expected_head_sha=request.expected_head_sha,
        expected_base_sha=request.expected_base_sha,
        current_main_sha=request.current_main_sha,
        authorization_id=request.authorization_id,
        invocation_id=invocation_id,
        confirmed=True,
    )


def _receipt_from_result(*, request, result, old_head_sha: str) -> PullRequestBranchRefreshReceipt:
    from scripts.agent_os_issue_labels.pr_branch_refresh import BranchRefreshStatus

    mutation_count = 1 if result.side_effects_performed else 0
    return PullRequestBranchRefreshReceipt(
        repository=request.repository,
        pr_number=request.pr_number,
        status=result.status.value,
        authorization_id=request.authorization_id,
        authorization_consumed=mutation_count == 1,
        admitted_main_sha=request.current_main_sha,
        old_head_sha=old_head_sha,
        new_head_sha=result.final_head_sha,
        mutation_count=mutation_count,
        validation_status=result.validation_status,
        validation_head_sha=result.validation_head_sha,
        lifecycle_reconciliation_status=result.lifecycle_reconciliation_status,
        final_current_proven=result.final_current_proven,
        blockers=result.blockers,
        reason_codes=tuple(item.value for item in result.reason_codes),
        rollback_posture=result.rollback_posture,
        side_effects_performed=result.side_effects_performed,
    )
