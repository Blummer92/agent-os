"""Finite PR-label adapter using the canonical Agent OS GitHub requester.

The Scheduler approval gate remains the authorization owner. This adapter owns
only payload validation, the fixed label-add endpoint, and Scheduler result
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
_DEFAULT_RETRY_AFTER_SECONDS = 5.0


class GitHubPRLabelAdapterError(Exception):
    def __init__(
        self,
        message: str,
        is_transient: bool = False,
        retry_after: float = _DEFAULT_RETRY_AFTER_SECONDS,
    ):
        super().__init__(message)
        self.is_transient = is_transient
        self.retry_after = retry_after


def _transient_request_error(error: GitHubRequestError) -> bool:
    status = error.status
    return (
        error.kind in {"rate-limited", "transport-unavailable"}
        or status == 429
        or (status is not None and 500 <= status < 600)
    )


class GitHubPRLabelAdapter(TaskAdapter):
    """Add one existing label to one PR after Scheduler approval."""

    def __init__(
        self,
        token: Optional[str] = None,
        http_post_label: Optional[
            Callable[[str, Dict[str, str], Dict[str, Any], float], Any]
        ] = None,
        timeout: float = 10.0,
    ):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout must be a finite positive number")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self._http_post_label = http_post_label
        self.timeout = timeout

    def execute(self, task: Task) -> Dict[str, Any]:
        payload = task.payload or {}
        try:
            action = self._require(payload, "action")
            handler = self.ACTIONS.get(action)
            if handler is None:
                raise GitHubPRLabelAdapterError(
                    f"Unsupported action: {action!r}. Supported: {sorted(self.ACTIONS)}"
                )
            return handler(self, payload)
        except GitHubPRLabelAdapterError as exc:
            if exc.is_transient:
                return {
                    "status": "retryable",
                    "message": str(exc),
                    "retry_after": exc.retry_after,
                }
            return {"status": "failure", "message": str(exc)}

    def _require(self, payload: Dict[str, Any], field: str) -> Any:
        if field not in payload or payload[field] in (None, ""):
            raise GitHubPRLabelAdapterError(
                f"Missing required payload field: {field!r}"
            )
        return payload[field]

    def _require_repository_full_name(self, payload: Dict[str, Any]) -> str:
        value = self._require(payload, "repository_full_name")
        if not isinstance(value, str):
            raise GitHubPRLabelAdapterError(
                f"'repository_full_name' must be a string, got {value!r}"
            )
        parts = value.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise GitHubPRLabelAdapterError(
                f"'repository_full_name' must be in 'owner/repo' shape, got {value!r}"
            )
        return value

    def _require_pr_number(self, payload: Dict[str, Any]) -> int:
        value = self._require(payload, "pr_number")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise GitHubPRLabelAdapterError(
                f"'pr_number' must be a positive integer, got {value!r}"
            )
        return value

    def _require_label(self, payload: Dict[str, Any]) -> str:
        value = self._require(payload, "label")
        if not isinstance(value, str) or not value.strip():
            raise GitHubPRLabelAdapterError("'label' must be a non-empty string")
        return value

    def _client(self) -> Github:
        auth = Auth.Token(self.token) if self.token else None
        return Github(
            auth=auth,
            retry=None,
            lazy=False,
            timeout=self.timeout,
            user_agent="workflow-scheduler/github-pr-label",
        )

    def _post_label(
        self, repository_full_name: str, pr_number: int, label: str
    ) -> Any:
        path = f"/repos/{repository_full_name}/issues/{pr_number}/labels"
        payload = {"labels": [label]}
        if self._http_post_label is not None:
            headers = {
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
            }
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            return self._http_post_label(
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
            raise GitHubPRLabelAdapterError(
                f"GitHub request failed: {error.kind}",
                is_transient=_transient_request_error(error),
            ) from error

    def _action_add_pr_label(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        repository_full_name = self._require_repository_full_name(payload)
        pr_number = self._require_pr_number(payload)
        label = self._require_label(payload)
        data = self._post_label(repository_full_name, pr_number, label)
        if not isinstance(data, list):
            raise GitHubPRLabelAdapterError(
                "GitHub API returned malformed label response: expected a list"
            )
        labels = []
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                raise GitHubPRLabelAdapterError(
                    f"GitHub API returned malformed label response: entry {index} is not an object"
                )
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                raise GitHubPRLabelAdapterError(
                    f"GitHub API returned malformed label response: entry {index} has invalid 'name'"
                )
            labels.append(name)
        return {
            "status": "success",
            "message": f"Added label {label!r} to {repository_full_name}#{pr_number}",
            "output": {"labels": labels},
        }

    ACTIONS: Dict[
        str, Callable[["GitHubPRLabelAdapter", Dict[str, Any]], Dict[str, Any]]
    ] = {"add_pr_label": _action_add_pr_label}
