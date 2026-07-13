"""Read-only GitHub REST API adapter.

Structural write safety: every network call in this module goes through
`_get()`, which only ever issues an HTTP GET. There is no POST, PATCH,
PUT, or DELETE call anywhere in this file, so it is structurally
impossible for this adapter to create/edit/comment/review/label/merge a
PR, create/delete a branch, edit a file, or push -- not a policy choice
enforced elsewhere, a property of the code itself.

Result shape (Phase 3F): returns the Phase 3D five-state contract
(status/message, from docs/ADAPTER_CONTRACT_FUTURE.md) rather than the
original success/error/is_transient shape used before this migration.
Retryable failures compute their own retry_after using the same
exponential-backoff formula Executor's RetryManager already applies
(5.0 * 2**retry_count, capped at 300.0), read from task.retry_count --
inlined here rather than imported, since importing RetryManager into
adapters would create a circular import with execution/executor.py
(which already imports TaskAdapter from this package). This preserves
the exact retry timing this adapter had before the migration; only the
result shape changed.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.models import Task

GITHUB_API_BASE = "https://api.github.com"

_TRANSIENT_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}


class GitHubReadOnlyAdapterError(Exception):
    """Raised internally for any controlled failure (bad payload, HTTP
    error, network error); always caught by execute() and turned into a
    Phase 3D five-state contract result (status="failure" or
    "retryable") -- never propagates."""

    def __init__(self, message: str, is_transient: bool = False):
        super().__init__(message)
        self.is_transient = is_transient


def _default_http_get(url: str, headers: Dict[str, str], timeout: float) -> Any:
    """Real network GET via stdlib urllib (no extra dependency). Returns
    the parsed JSON body. Raises GitHubReadOnlyAdapterError on any HTTP
    or network failure -- never a bare urllib/json exception."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        is_transient = exc.code in _TRANSIENT_HTTP_STATUS_CODES
        raise GitHubReadOnlyAdapterError(
            f"GitHub API returned HTTP {exc.code}: {exc.reason}", is_transient=is_transient
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubReadOnlyAdapterError(f"GitHub API connection error: {exc.reason}", is_transient=True) from exc
    except TimeoutError as exc:
        raise GitHubReadOnlyAdapterError(f"GitHub API request timed out: {exc}", is_transient=True) from exc
    except json.JSONDecodeError as exc:
        raise GitHubReadOnlyAdapterError(f"GitHub API returned invalid JSON: {exc}", is_transient=False) from exc


class GitHubReadOnlyAdapter(TaskAdapter):
    """Read-only GitHub adapter. Supported task.payload["action"] values:
    get_repo, get_pr_info, list_pr_changed_filenames, list_recent_prs,
    get_commit. See ACTIONS below for the exact handler per action.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        http_get: Optional[Callable[[str, Dict[str, str], float], Any]] = None,
        timeout: float = 10.0,
    ):
        """Args:
        token: GitHub token for Authorization header. Falls back to the
            GITHUB_TOKEN environment variable, then to unauthenticated
            requests (works for public repos, subject to lower rate limits).
        http_get: Injectable GET function, signature
            (url, headers, timeout) -> parsed JSON body, raising
            GitHubReadOnlyAdapterError on failure. Defaults to a real
            urllib-based implementation; tests inject a fake here.
        timeout: Per-request timeout in seconds.
        """
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self._http_get = http_get or _default_http_get
        self.timeout = timeout

    def execute(self, task: Task) -> Dict[str, Any]:
        payload = task.payload or {}
        try:
            action = self._require(payload, "action")
            handler = self.ACTIONS.get(action)
            if handler is None:
                raise GitHubReadOnlyAdapterError(
                    f"Unsupported action: {action!r}. Supported: {sorted(self.ACTIONS)}"
                )
            output = handler(self, payload)
            return {"status": "success", "message": f"GitHub {action!r} succeeded", "output": output}
        except GitHubReadOnlyAdapterError as exc:
            if exc.is_transient:
                retry_after = min(5.0 * (2 ** task.retry_count), 300.0)
                return {"status": "retryable", "message": str(exc), "retry_after": retry_after}
            return {"status": "failure", "message": str(exc)}

    # -- payload helpers ------------------------------------------------

    def _require(self, payload: Dict[str, Any], field: str) -> Any:
        if field not in payload or payload[field] in (None, ""):
            raise GitHubReadOnlyAdapterError(f"Missing required payload field: {field!r}")
        return payload[field]

    def _require_pr_number(self, payload: Dict[str, Any]) -> int:
        value = self._require(payload, "pr_number")
        if isinstance(value, bool) or not isinstance(value, int):
            raise GitHubReadOnlyAdapterError(f"'pr_number' must be an integer, got {value!r}")
        return value

    def _get(self, path: str) -> Any:
        """The only place an HTTP request is issued -- always GET."""
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return self._http_get(f"{GITHUB_API_BASE}{path}", headers, self.timeout)

    # -- action handlers --------------------------------------------------

    def _action_get_repo(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        full_name = self._require(payload, "repository_full_name")
        data = self._get(f"/repos/{full_name}")
        return {
            "full_name": data.get("full_name"),
            "description": data.get("description"),
            "default_branch": data.get("default_branch"),
            "stargazers_count": data.get("stargazers_count"),
            "open_issues_count": data.get("open_issues_count"),
            "private": data.get("private"),
        }

    def _action_get_pr_info(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        full_name = self._require(payload, "repository_full_name")
        pr_number = self._require_pr_number(payload)
        data = self._get(f"/repos/{full_name}/pulls/{pr_number}")
        return {
            "number": data.get("number"),
            "title": data.get("title"),
            "state": data.get("state"),
            "body": data.get("body"),
            "user": (data.get("user") or {}).get("login"),
            "merged": data.get("merged"),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }

    def _action_list_pr_changed_filenames(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        full_name = self._require(payload, "repository_full_name")
        pr_number = self._require_pr_number(payload)
        data = self._get(f"/repos/{full_name}/pulls/{pr_number}/files")
        filenames = [item.get("filename") for item in data if isinstance(item, dict)]
        return {"filenames": filenames}

    def _action_list_recent_prs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        full_name = self._require(payload, "repository_full_name")
        state = payload.get("state", "all")
        limit = payload.get("limit", 10)
        data = self._get(f"/repos/{full_name}/pulls?state={state}&sort=created&direction=desc&per_page={limit}")
        summaries = [
            {"number": pr.get("number"), "title": pr.get("title"), "state": pr.get("state")}
            for pr in data
            if isinstance(pr, dict)
        ]
        return {"pull_requests": summaries}

    def _action_get_commit(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        full_name = self._require(payload, "repository_full_name")
        sha = self._require(payload, "sha")
        data = self._get(f"/repos/{full_name}/commits/{sha}")
        commit = data.get("commit") or {}
        author = commit.get("author") or {}
        return {
            "sha": data.get("sha"),
            "message": commit.get("message"),
            "author": author.get("name"),
            "date": author.get("date"),
        }

    ACTIONS: Dict[str, Callable[["GitHubReadOnlyAdapter", Dict[str, Any]], Dict[str, Any]]] = {
        "get_repo": _action_get_repo,
        "get_pr_info": _action_get_pr_info,
        "list_pr_changed_filenames": _action_list_pr_changed_filenames,
        "list_recent_prs": _action_list_recent_prs,
        "get_commit": _action_get_commit,
    }
