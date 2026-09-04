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
    """Reuse the repository's existing GITHUB_TOKEN/GH_TOKEN convention."""

    token = environment.get("GITHUB_TOKEN") or environment.get("GH_TOKEN")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("GITHUB_TOKEN or GH_TOKEN is required")

    from github import Auth, Github

    return Github(auth=Auth.Token(token.strip()))


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


def run_branch_refresh_operator(
    *,
    request: object,
    repository_root: str,
    invocation_id: str,
    environment: Mapping[str, str],
):
    """Concrete #1365 operator composition; consumes but never grants authority."""

    from scripts.agent_os_issue_labels.pr_branch_refresh import PullRequestBranchRefreshRequest
    from scripts.agent_os_issue_labels.pr_branch_refresh_provider import (
        run_production_pull_request_branch_refresh,
    )

    if not isinstance(request, PullRequestBranchRefreshRequest):
        raise TypeError("request must be exact PullRequestBranchRefreshRequest")
    if not request.authorization_current or not request.branch_refresh_authorized:
        raise RuntimeError("current branch-refresh authorization is required")
    if not isinstance(invocation_id, str) or not invocation_id.strip():
        raise ValueError("invocation_id is required")

    github_client = build_branch_refresh_github_client(environment)
    runner = SubprocessBranchUpdateRunner()
    validation = ClosedBranchRefreshValidationExecutor(
        runner=runner,
        repository_root=repository_root,
    )
    reviews = PyGithubBlockingReviewThreadsReader(github_client)

    preflight = preflight_production_branch_refresh(
        github_client=github_client,
        request=request,
        repository_root=repository_root,
    )
    if not preflight.ready:
        raise RuntimeError(
            "branch refresh preflight blocked: " + ",".join(preflight.reason_codes)
        )

    return run_production_pull_request_branch_refresh(
        github_client=github_client,
        runner=runner,
        validation_executor=validation,
        review_threads_reader=reviews,
        request=request,
        repository_root=repository_root,
        invocation_id=invocation_id,
        environment=environment,
    )


def refresh_pr(
    *,
    repository: str,
    pr_number: int,
    expected_head_sha: str,
    current_main_sha: str,
    authorization_id: str,
    authorization_current: bool,
    branch_refresh_authorized: bool,
    allowed_changed_paths: tuple[str, ...],
    forbidden_paths: tuple[str, ...],
    label_write_authorized: bool,
    repository_root: str,
    invocation_id: str,
    environment: Mapping[str, str],
) -> PullRequestBranchRefreshReceipt:
    """Canonical operator-facing facade for one governed PR refresh request."""

    from scripts.agent_os_issue_labels.pr_branch_refresh import (
        PullRequestBranchRefreshRequest,
        _validate_request,
    )

    for name, value in (
        ("authorization_current", authorization_current),
        ("branch_refresh_authorized", branch_refresh_authorized),
        ("label_write_authorized", label_write_authorized),
    ):
        if type(value) is not bool:
            raise TypeError(f"{name} must be an exact boolean")
    for name, value in (
        ("allowed_changed_paths", allowed_changed_paths),
        ("forbidden_paths", forbidden_paths),
    ):
        if type(value) is not tuple or any(type(item) is not str or not item for item in value):
            raise TypeError(f"{name} must be a tuple of non-empty strings")
    if not isinstance(repository_root, str) or not repository_root:
        raise ValueError("repository_root is required")
    if not isinstance(invocation_id, str) or not invocation_id.strip():
        raise ValueError("invocation_id is required")
    if not isinstance(environment, Mapping):
        raise TypeError("environment must be a mapping")

    request = PullRequestBranchRefreshRequest(
        repository=repository,
        pr_number=pr_number,
        base_branch="main",
        expected_base_sha=current_main_sha,
        expected_head_sha=expected_head_sha,
        current_main_sha=current_main_sha,
        authorization_id=authorization_id,
        authorization_current=authorization_current,
        allowed_changed_paths=allowed_changed_paths,
        forbidden_paths=forbidden_paths,
        required_validation_command_ids=_CANONICAL_REFRESH_VALIDATION_COMMAND_IDS,
        branch_refresh_authorized=branch_refresh_authorized,
        label_write_authorized=label_write_authorized,
    )
    _validate_request(request)

    if not authorization_current or not branch_refresh_authorized:
        return _blocked_refresh_receipt(
            request=request,
            reason_codes=("authorization.refresh-required",),
        )

    try:
        result = run_branch_refresh_operator(
            request=request,
            repository_root=repository_root,
            invocation_id=invocation_id,
            environment=environment,
        )
    except RuntimeError as error:
        prefix = "branch refresh preflight blocked: "
        message = str(error)
        if not message.startswith(prefix):
            raise
        reasons = tuple(item for item in message[len(prefix):].split(",") if item)
        return _blocked_refresh_receipt(request=request, reason_codes=reasons)

    return _receipt_from_result(
        result=result,
        authorization_id=authorization_id,
        admitted_main_sha=current_main_sha,
    )


def _blocked_refresh_receipt(
    *,
    request: object,
    reason_codes: tuple[str, ...],
) -> PullRequestBranchRefreshReceipt:
    return PullRequestBranchRefreshReceipt(
        repository=request.repository,
        pr_number=request.pr_number,
        status="blocked",
        authorization_id=request.authorization_id,
        authorization_consumed=False,
        admitted_main_sha=request.current_main_sha,
        old_head_sha=request.expected_head_sha,
        new_head_sha=None,
        mutation_count=0,
        validation_status=None,
        validation_head_sha=None,
        lifecycle_reconciliation_status=None,
        final_current_proven=False,
        blockers=tuple(sorted(set(reason_codes))),
        reason_codes=tuple(sorted(set(reason_codes))),
        rollback_posture="no-branch-mutation",
        side_effects_performed=False,
    )


def _receipt_from_result(
    *,
    result: object,
    authorization_id: str,
    admitted_main_sha: str,
) -> PullRequestBranchRefreshReceipt:
    from scripts.agent_os_issue_labels.pr_branch_refresh import PullRequestBranchRefreshResult

    if not isinstance(result, PullRequestBranchRefreshResult):
        raise TypeError("operator returned an invalid branch-refresh result")

    validation = result.validation
    lifecycle = result.lifecycle_reconciliation
    reasons = tuple(result.reason_codes)
    blockers = () if result.status == "converged" else reasons
    side_effects = bool(result.side_effects_performed)
    mutation_attempted = bool(result.mutation_attempted or side_effects)
    return PullRequestBranchRefreshReceipt(
        repository=result.repository,
        pr_number=result.pr_number,
        status=result.status,
        authorization_id=authorization_id,
        authorization_consumed=mutation_attempted,
        admitted_main_sha=admitted_main_sha,
        old_head_sha=result.old_head_sha,
        new_head_sha=result.new_head_sha,
        mutation_count=1 if mutation_attempted else 0,
        validation_status=None if validation is None else validation.status,
        validation_head_sha=None if validation is None else validation.head_sha,
        lifecycle_reconciliation_status=(
            None if lifecycle is None else lifecycle.reconciliation_status
        ),
        final_current_proven="branch.current-proven" in reasons,
        blockers=blockers,
        reason_codes=reasons,
        rollback_posture=(
            "restore-old-head-with-separate-authorization"
            if side_effects
            else "separate-authorization-required"
            if mutation_attempted
            else "no-branch-mutation"
        ),
        side_effects_performed=side_effects,
    )
