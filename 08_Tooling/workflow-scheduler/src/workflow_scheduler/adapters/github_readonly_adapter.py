"""Read-only GitHub REST API adapter."""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.models import Task

GITHUB_API_BASE = "https://api.github.com"
_TRANSIENT_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}

_VALID_PR_LIST_STATES = {"open", "closed", "all"}
_MAX_RECENT_PRS_LIMIT = 100


class GitHubReadOnlyAdapterError(Exception):
    def __init__(self, message: str, is_transient: bool = False):
        super().__init__(message)
        self.is_transient = is_transient


def _default_http_get(url: str, headers: Dict[str, str], timeout: float) -> Any:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise GitHubReadOnlyAdapterError(
            f"GitHub API returned HTTP {exc.code}: {exc.reason}",
            is_transient=exc.code in _TRANSIENT_HTTP_STATUS_CODES,
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubReadOnlyAdapterError(f"GitHub API connection error: {exc.reason}", is_transient=True) from exc
    except TimeoutError as exc:
        raise GitHubReadOnlyAdapterError(f"GitHub API request timed out: {exc}", is_transient=True) from exc
    except json.JSONDecodeError as exc:
        raise GitHubReadOnlyAdapterError(f"GitHub API returned invalid JSON: {exc}") from exc


class GitHubReadOnlyAdapter(TaskAdapter):
    def __init__(self, token: Optional[str] = None, http_get: Optional[Callable[[str, Dict[str, str], float], Any]] = None, timeout: float = 10.0):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout must be a finite positive number")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self._http_get = http_get or _default_http_get
        self.timeout = timeout

    def execute(self, task: Task) -> Dict[str, Any]:
        payload = task.payload or {}
        try:
            action = self._require(payload, "action")
            handler = self.ACTIONS.get(action)
            if handler is None:
                raise GitHubReadOnlyAdapterError(f"Unsupported action: {action!r}. Supported: {sorted(self.ACTIONS)}")
            output = handler(self, payload)
            return {"status": "success", "message": f"GitHub {action!r} succeeded", "output": output}
        except GitHubReadOnlyAdapterError as exc:
            if exc.is_transient:
                return {"status": "retryable", "message": str(exc), "retry_after": min(5.0 * (2 ** task.retry_count), 300.0)}
            return {"status": "failure", "message": str(exc)}

    def _require(self, payload: Dict[str, Any], field: str) -> Any:
        if field not in payload or payload[field] in (None, ""):
            raise GitHubReadOnlyAdapterError(f"Missing required payload field: {field!r}")
        return payload[field]

    def _require_repository_full_name(self, payload: Dict[str, Any]) -> str:
        value = self._require(payload, "repository_full_name")
        if not isinstance(value, str):
            raise GitHubReadOnlyAdapterError(f"'repository_full_name' must be a string, got {value!r}")
        parts = value.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise GitHubReadOnlyAdapterError(
                f"'repository_full_name' must be in 'owner/repo' shape, got {value!r}"
            )
        return value

    def _require_pr_number(self, payload: Dict[str, Any]) -> int:
        value = self._require(payload, "pr_number")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise GitHubReadOnlyAdapterError(f"'pr_number' must be a positive integer, got {value!r}")
        return value

    def _get(self, path: str) -> Any:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return self._http_get(f"{GITHUB_API_BASE}{path}", headers, self.timeout)

    def _action_get_repo(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        full_name = self._require_repository_full_name(payload)
        data = self._get(f"/repos/{full_name}")
        return {key: data.get(key) for key in ("full_name", "description", "default_branch", "stargazers_count", "open_issues_count", "private")}

    def _action_get_pr_info(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        full_name = self._require_repository_full_name(payload)
        data = self._get(f"/repos/{full_name}/pulls/{self._require_pr_number(payload)}")
        return {"number": data.get("number"), "title": data.get("title"), "state": data.get("state"), "body": data.get("body"), "user": (data.get("user") or {}).get("login"), "merged": data.get("merged"), "created_at": data.get("created_at"), "updated_at": data.get("updated_at")}

    def _action_list_pr_changed_filenames(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        full_name = self._require_repository_full_name(payload)
        data = self._get(f"/repos/{full_name}/pulls/{self._require_pr_number(payload)}/files")
        return {"filenames": [item.get("filename") for item in data if isinstance(item, dict)]}

    def _action_list_recent_prs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        full_name = self._require_repository_full_name(payload)
        state = payload.get("state", "all")
        if not isinstance(state, str) or state not in _VALID_PR_LIST_STATES:
            raise GitHubReadOnlyAdapterError(
                f"'state' must be one of {sorted(_VALID_PR_LIST_STATES)}, got {state!r}"
            )
        limit = payload.get("limit", 10)
        if isinstance(limit, bool) or not isinstance(limit, int) or not (1 <= limit <= _MAX_RECENT_PRS_LIMIT):
            raise GitHubReadOnlyAdapterError(
                f"'limit' must be an integer between 1 and {_MAX_RECENT_PRS_LIMIT}, got {limit!r}"
            )
        data = self._get(f"/repos/{full_name}/pulls?state={state}&sort=created&direction=desc&per_page={limit}")
        return {"pull_requests": [{"number": pr.get("number"), "title": pr.get("title"), "state": pr.get("state")} for pr in data if isinstance(pr, dict)]}

    def _action_get_commit(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        full_name = self._require_repository_full_name(payload)
        data = self._get(f"/repos/{full_name}/commits/{self._require(payload, 'sha')}")
        commit = data.get("commit") or {}
        author = commit.get("author") or {}
        return {"sha": data.get("sha"), "message": commit.get("message"), "author": author.get("name"), "date": author.get("date")}

    ACTIONS: Dict[str, Callable[["GitHubReadOnlyAdapter", Dict[str, Any]], Dict[str, Any]]] = {
        "get_repo": _action_get_repo,
        "get_pr_info": _action_get_pr_info,
        "list_pr_changed_filenames": _action_list_pr_changed_filenames,
        "list_recent_prs": _action_list_recent_prs,
        "get_commit": _action_get_commit,
    }
