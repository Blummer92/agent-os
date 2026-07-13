"""GitHub PR comment adapter -- the first write-capable adapter.

Structural write safety: this adapter has exactly one HTTP call site,
`_post_comment()`, which always issues a POST to exactly one hardcoded
URL template: `/repos/{repository_full_name}/issues/{pr_number}/comments`
(GitHub's PR-comment-creation endpoint; PR comments are created through
the issues API). The path is built only from caller-supplied
`repository_full_name` and `pr_number` values substituted into that
fixed template -- never a caller-supplied raw path or HTTP method. There
is no GET, PATCH, PUT, or DELETE call anywhere in this file, and no
other POST target is reachable: no comment editing, no comment deletion,
no reviews, no inline review comments, no labels, no merges, no branch
create/delete, no file edits, no pushes, no issue edits.

Governance boundary: this adapter does NOT itself check approval status
-- it has no awareness of approval at all. Write-safety here comes
entirely from the scheduler's existing governance layer
(StopConditionChecker + Executor.execute() in governance/
stop_conditions.py and execution/executor.py): a task with
`approval_required=True` is intercepted by APPROVAL_ENGINE_DEFERRED and
never reaches `adapter.execute()` until an ApprovalRequest for that task
has decision=APPROVED; a rejected request hard-blocks the task
(GOVERNANCE_BLOCKED) instead. This adapter is only ever invoked after
that gate has already passed -- the same architecture already proven by
the fake-never-called adapter tests in Phase 2F, applied here to a real
write for the first time.
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


class GitHubPRCommentAdapterError(Exception):
    """Raised internally for any controlled failure (bad payload, HTTP
    error, network error); always caught by execute() and turned into a
    normal {"success": False, ...} result -- never propagates."""

    def __init__(self, message: str, is_transient: bool = False):
        super().__init__(message)
        self.is_transient = is_transient


def _default_http_post_comment(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: float) -> Any:
    """Real network POST via stdlib urllib (no extra dependency). Returns
    the parsed JSON body. Raises GitHubPRCommentAdapterError on any HTTP
    or network failure -- never a bare urllib/json exception. This is the
    only place this module ever performs a write."""
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        is_transient = exc.code in _TRANSIENT_HTTP_STATUS_CODES
        raise GitHubPRCommentAdapterError(
            f"GitHub API returned HTTP {exc.code}: {exc.reason}", is_transient=is_transient
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubPRCommentAdapterError(f"GitHub API connection error: {exc.reason}", is_transient=True) from exc
    except TimeoutError as exc:
        raise GitHubPRCommentAdapterError(f"GitHub API request timed out: {exc}", is_transient=True) from exc
    except json.JSONDecodeError as exc:
        raise GitHubPRCommentAdapterError(f"GitHub API returned invalid JSON: {exc}", is_transient=False) from exc


class GitHubPRCommentAdapter(TaskAdapter):
    """Write-capable GitHub adapter with exactly one supported
    task.payload["action"] value: post_pr_comment. Posts a single
    top-level comment on an existing PR. Relies entirely on the
    scheduler's approval gate (see module docstring) to ensure this is
    only ever called for an approved task -- performs no approval check
    of its own.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        http_post_comment: Optional[Callable[[str, Dict[str, str], Dict[str, Any], float], Any]] = None,
        timeout: float = 10.0,
    ):
        """Args:
        token: GitHub token for the Authorization header. Falls back to
            the GITHUB_TOKEN environment variable. Unlike the read-only
            GitHub adapter, there is no meaningful unauthenticated mode
            here -- posting a comment always requires a token with
            write scope -- so a missing/insufficient token surfaces as
            a normal HTTP 401/403 failure from the API, not a local
            validation error.
        http_post_comment: Injectable POST function, signature
            (url, headers, body, timeout) -> parsed JSON body, raising
            GitHubPRCommentAdapterError on failure. Defaults to a real
            urllib-based implementation; tests inject a fake here so no
            live GitHub access or real token is ever required in tests.
        timeout: Per-request timeout in seconds.
        """
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self._http_post_comment = http_post_comment or _default_http_post_comment
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
            output = handler(self, payload)
            return {"success": True, "error": None, "output": output}
        except GitHubPRCommentAdapterError as exc:
            return {"success": False, "error": str(exc), "is_transient": exc.is_transient}

    # -- payload helpers ------------------------------------------------

    def _require(self, payload: Dict[str, Any], field: str) -> Any:
        if field not in payload or payload[field] in (None, ""):
            raise GitHubPRCommentAdapterError(f"Missing required payload field: {field!r}")
        return payload[field]

    def _require_pr_number(self, payload: Dict[str, Any]) -> int:
        value = self._require(payload, "pr_number")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise GitHubPRCommentAdapterError(f"'pr_number' must be a positive integer, got {value!r}")
        return value

    def _require_body(self, payload: Dict[str, Any]) -> str:
        value = self._require(payload, "body")
        if not isinstance(value, str) or not value.strip():
            raise GitHubPRCommentAdapterError("'body' must be a non-empty string")
        return value

    def _post_comment(self, repository_full_name: str, pr_number: int, body: str) -> Any:
        """The only HTTP call site in this module -- always POST, always
        this one fixed URL template. repository_full_name and pr_number
        are substituted into the template; nothing else about the
        request (path or method) is caller-controlled."""
        url = f"{GITHUB_API_BASE}/repos/{repository_full_name}/issues/{pr_number}/comments"
        headers = {"Accept": "application/vnd.github+json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return self._http_post_comment(url, headers, {"body": body}, self.timeout)

    # -- action handlers --------------------------------------------------

    def _action_post_pr_comment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        repository_full_name = self._require(payload, "repository_full_name")
        pr_number = self._require_pr_number(payload)
        body = self._require_body(payload)
        data = self._post_comment(repository_full_name, pr_number, body)
        return {
            "id": data.get("id"),
            "html_url": data.get("html_url"),
            "created_at": data.get("created_at"),
        }

    ACTIONS: Dict[str, Callable[["GitHubPRCommentAdapter", Dict[str, Any]], Dict[str, Any]]] = {
        "post_pr_comment": _action_post_pr_comment,
    }
