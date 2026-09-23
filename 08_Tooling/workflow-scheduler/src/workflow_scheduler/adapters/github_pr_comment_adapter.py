"""Finite PR-comment adapter using the canonical Agent OS GitHub requester.

The Scheduler approval gate remains the authorization owner. This adapter owns
only payload validation, the fixed PR-comment endpoint, and Scheduler result
projection. Tests may inject the historical callable seam; production uses the
shared PyGithub request boundary from agent_os_github_issue_provider.
"""
from __future__ import annotations

import math
import os
from typing import Any, Callable, Dict, Optional

from github import Auth, Github

from scripts.agent_os_github_issue_provider.request import (
    GitHubRequestError,
    request_json,
)
from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.models import Task

GITHUB_API_BASE = "https://api.github.com"


class GitHubPRCommentAdapterError(Exception):
    def __init__(self, message: str, is_transient: bool = False):
        super().__init__(message)
        self.is_transient = is_transient


def _transient_request_error(error: GitHubRequestError) -> bool:
    status = error.status
    return (
        error.kind in {"rate-limited", "transport-unavailable"}
        or status == 429
        or (status is not None and 500 <= status < 600)
    )


class GitHubPRCommentAdapter(TaskAdapter):
    """Post one top-level PR comment after Scheduler approval."""

    def __init__(
        self,
        token: Optional[str] = None,
        http_post_comment: Optional[
            Callable[[str, Dict[str, str], Dict[str, Any], float], Any]
        ] = None,
        timeout: float = 10.0,
    ):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout must be a finite positive number")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self._http_post_comment = http_post_comment
        self.timeout = timeout

    def execute(self, task: Task) -> Dict[str, Any]:
        payload = task.payload or {}
        try:
            action = self._require(payload, "action")
            handler = self.ACTIONS.get(action)
            if handler is None:
                raise GitHubPRCommentAdapterError(
                    f"Unsupported action: {action!r}. Supported: {sorted(self.ACTIONS)}"
                )
            return handler(self, payload)
        except GitHubPRCommentAdapterError as exc:
            if exc.is_transient:
                retry_after = min(5.0 * (2 ** task.retry_count), 300.0)
                return {
                    "status": "retryable",
                    "message": str(exc),
                    "retry_after": retry_after,
                }
            return {"status": "failure", "message": str(exc)}

    def _require(self, payload: Dict[str, Any], field: str) -> Any:
        if field not in payload or payload[field] in (None, ""):
            raise GitHubPRCommentAdapterError(
                f"Missing required payload field: {field!r}"
            )
        return payload[field]

    def _require_repository_full_name(self, payload: Dict[str, Any]) -> str:
        value = self._require(payload, "repository_full_name")
        if not isinstance(value, str):
            raise GitHubPRCommentAdapterError(
                f"'repository_full_name' must be a string, got {value!r}"
            )
        parts = value.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise GitHubPRCommentAdapterError(
                f"'repository_full_name' must be in 'owner/repo' shape, got {value!r}"
            )
        return value

    def _require_pr_number(self, payload: Dict[str, Any]) -> int:
        value = self._require(payload, "pr_number")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise GitHubPRCommentAdapterError(
                f"'pr_number' must be a positive integer, got {value!r}"
            )
        return value

    def _require_body(self, payload: Dict[str, Any]) -> str:
        value = self._require(payload, "body")
        if not isinstance(value, str) or not value.strip():
            raise GitHubPRCommentAdapterError("'body' must be a non-empty string")
        return value

    def _client(self) -> Github:
        auth = Auth.Token(self.token) if self.token else None
        return Github(
            auth=auth,
            retry=None,
            lazy=False,
            timeout=self.timeout,
            user_agent="workflow-scheduler/github-pr-comment",
        )

    def _post_comment(
        self, repository_full_name: str, pr_number: int, body: str
    ) -> Any:
        path = f"/repos/{repository_full_name}/issues/{pr_number}/comments"
        payload = {"body": body}
        if self._http_post_comment is not None:
            headers = {
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
            }
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            return self._http_post_comment(
                f"{GITHUB_API_BASE}{path}", headers, payload, self.timeout
            )
        try:
            return request_json(
                self._client(),
                "POST",
                path,
                input_payload=payload,
                max_attempts=1,
            ).payload
        except GitHubRequestError as error:
            raise GitHubPRCommentAdapterError(
                f"GitHub request failed: {error.kind}",
                is_transient=_transient_request_error(error),
            ) from error

    def _action_post_pr_comment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        repository_full_name = self._require_repository_full_name(payload)
        pr_number = self._require_pr_number(payload)
        body = self._require_body(payload)
        data = self._post_comment(repository_full_name, pr_number, body)
        if not isinstance(data, dict):
            raise GitHubPRCommentAdapterError(
                "GitHub comment POST completed but returned malformed response evidence; "
                "manual reconciliation is required before any retry"
            )
        return {
            "status": "success",
            "message": f"Posted comment on {repository_full_name}#{pr_number}",
            "output": {
                "id": data.get("id"),
                "html_url": data.get("html_url"),
                "created_at": data.get("created_at"),
            },
        }

    ACTIONS: Dict[
        str, Callable[["GitHubPRCommentAdapter", Dict[str, Any]], Dict[str, Any]]
    ] = {"post_pr_comment": _action_post_pr_comment}
