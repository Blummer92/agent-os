"""GitHub PR label adapter -- the second write-capable adapter, and the
first real adapter to use the Phase 3D five-state result contract
(status/message, from docs/ADAPTER_CONTRACT_FUTURE.md) instead of the
original success/error/is_transient shape.

Structural write safety: this adapter has exactly one HTTP call site,
`_post_label()`, which always issues a POST to exactly one hardcoded URL
template: `/repos/{repository_full_name}/issues/{pr_number}/labels`
(GitHub's label-add endpoint; PR labels are added through the issues
API, since a PR is an issue for labeling purposes). Posting a labels
array to this endpoint ADDS the given label without removing any
existing label -- it never replaces or clears the label set. The path
is built only from caller-supplied `repository_full_name` and
`pr_number` substituted into that fixed template -- never a
caller-supplied raw path or HTTP method. There is no GET, PATCH, PUT, or
DELETE call anywhere in this file, and no other POST target is
reachable: no label creation/deletion/editing/removal, no issue title/
body edits, no PR metadata edits, no comments, no reviews, no merges,
no branch operations, no file edits, no pushes.

Governance boundary: this adapter does NOT itself check approval status
-- it has no awareness of approval at all, exactly like the Phase 3C PR
comment adapter. Write-safety comes entirely from the scheduler's
existing governance layer (StopConditionChecker + Executor.execute()):
a task with `approval_required=True` is intercepted by
APPROVAL_ENGINE_DEFERRED and never reaches `adapter.execute()` until an
ApprovalRequest for that task has decision=APPROVED; a rejected request
hard-blocks the task (GOVERNANCE_BLOCKED) instead. This adapter is only
ever invoked after that gate has already passed.
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
_DEFAULT_RETRY_AFTER_SECONDS = 5.0


class GitHubPRLabelAdapterError(Exception):
    """Raised internally for any controlled failure (bad payload, HTTP
    error, network error); always caught by execute() and turned into a
    Phase 3D five-state contract result (status="failure" or
    "retryable") -- never propagates."""

    def __init__(
        self,
        message: str,
        is_transient: bool = False,
        retry_after: float = _DEFAULT_RETRY_AFTER_SECONDS,
    ):
        super().__init__(message)
        self.is_transient = is_transient
        self.retry_after = retry_after


def _default_http_post_label(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: float) -> Any:
    """Real network POST via stdlib urllib (no extra dependency). Returns
    the parsed JSON body. Raises GitHubPRLabelAdapterError on any HTTP or
    network failure -- never a bare urllib/json exception. This is the
    only place this module ever performs a write."""
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        is_transient = exc.code in _TRANSIENT_HTTP_STATUS_CODES
        raise GitHubPRLabelAdapterError(
            f"GitHub API returned HTTP {exc.code}: {exc.reason}", is_transient=is_transient
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubPRLabelAdapterError(f"GitHub API connection error: {exc.reason}", is_transient=True) from exc
    except TimeoutError as exc:
        raise GitHubPRLabelAdapterError(f"GitHub API request timed out: {exc}", is_transient=True) from exc
    except json.JSONDecodeError as exc:
        raise GitHubPRLabelAdapterError(f"GitHub API returned invalid JSON: {exc}", is_transient=False) from exc


class GitHubPRLabelAdapter(TaskAdapter):
    """Write-capable GitHub adapter with exactly one supported
    task.payload["action"] value: add_pr_label. Adds a single existing
    label to an existing PR. Returns the Phase 3D five-state result
    contract (status/message, ...) instead of the original success/
    error/is_transient shape -- see docs/ADAPTER_CONTRACT_FUTURE.md.
    Relies entirely on the scheduler's approval gate (see module
    docstring) to ensure this is only ever called for an approved task
    -- performs no approval check of its own.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        http_post_label: Optional[Callable[[str, Dict[str, str], Dict[str, Any], float], Any]] = None,
        timeout: float = 10.0,
    ):
        """Args:
        token: GitHub token for the Authorization header. Falls back to
            the GITHUB_TOKEN environment variable. There is no
            meaningful unauthenticated mode here -- adding a label
            always requires a token with write scope -- so a missing/
            insufficient token surfaces as a normal HTTP 401/403 failure
            from the API, not a local validation error.
        http_post_label: Injectable POST function, signature
            (url, headers, body, timeout) -> parsed JSON body, raising
            GitHubPRLabelAdapterError on failure. Defaults to a real
            urllib-based implementation; tests inject a fake here so no
            live GitHub access or real token is ever required in tests.
        timeout: Per-request timeout in seconds.
        """
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self._http_post_label = http_post_label or _default_http_post_label
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
                return {"status": "retryable", "message": str(exc), "retry_after": exc.retry_after}
            return {"status": "failure", "message": str(exc)}

    # -- payload helpers ------------------------------------------------

    def _require(self, payload: Dict[str, Any], field: str) -> Any:
        if field not in payload or payload[field] in (None, ""):
            raise GitHubPRLabelAdapterError(f"Missing required payload field: {field!r}")
        return payload[field]

    def _require_repository_full_name(self, payload: Dict[str, Any]) -> str:
        value = self._require(payload, "repository_full_name")
        if not isinstance(value, str):
            raise GitHubPRLabelAdapterError(f"'repository_full_name' must be a string, got {value!r}")
        parts = value.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise GitHubPRLabelAdapterError(
                f"'repository_full_name' must be in 'owner/repo' shape, got {value!r}"
            )
        return value

    def _require_pr_number(self, payload: Dict[str, Any]) -> int:
        value = self._require(payload, "pr_number")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise GitHubPRLabelAdapterError(f"'pr_number' must be a positive integer, got {value!r}")
        return value

    def _require_label(self, payload: Dict[str, Any]) -> str:
        value = self._require(payload, "label")
        if not isinstance(value, str) or not value.strip():
            raise GitHubPRLabelAdapterError("'label' must be a non-empty string")
        return value

    def _post_label(self, repository_full_name: str, pr_number: int, label: str) -> Any:
        """The only HTTP call site in this module -- always POST, always
        this one fixed URL template. repository_full_name and pr_number
        are substituted into the template; nothing else about the
        request (path or method) is caller-controlled. GitHub treats a
        PR as an issue for labeling purposes, hence the /issues/ path."""
        url = f"{GITHUB_API_BASE}/repos/{repository_full_name}/issues/{pr_number}/labels"
        headers = {"Accept": "application/vnd.github+json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return self._http_post_label(url, headers, {"labels": [label]}, self.timeout)

    # -- action handlers --------------------------------------------------

    def _action_add_pr_label(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        repository_full_name = self._require_repository_full_name(payload)
        pr_number = self._require_pr_number(payload)
        label = self._require_label(payload)
        data = self._post_label(repository_full_name, pr_number, label)
        labels = [item.get("name") for item in data if isinstance(item, dict)] if isinstance(data, list) else []
        return {
            "status": "success",
            "message": f"Added label {label!r} to {repository_full_name}#{pr_number}",
            "output": {"labels": labels},
        }

    ACTIONS: Dict[str, Callable[["GitHubPRLabelAdapter", Dict[str, Any]], Dict[str, Any]]] = {
        "add_pr_label": _action_add_pr_label,
    }
