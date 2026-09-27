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


def _default_http_get(path: str, token: Optional[str], timeout: float) -> Any:
    """Use the canonical Agent OS PyGithub requester for one bounded GET."""
    del timeout  # PyGithub owns its configured request timeout at the client boundary.
    environment = dict(os.environ)
    if token is not None:
        environment["GITHUB_TOKEN"] = token
    try:
        client = build_token_client(environment, user_agent="agent-os-workflow-scheduler/1")
        return request_json(
            client,
            "GET",
            path,
            max_attempts=1,
        ).payload
    except GitHubRequestError as exc:
        status = exc.status
        transient = exc.kind in {"rate-limited", "transport-unavailable"} or (
            status is not None and status in {429, 500, 502, 503, 504}
        )
        raise GitHubReadOnlyAdapterError(
            f"GitHub API request failed: {exc.kind}" + (f" (HTTP {status})" if status is not None else ""),
            is_transient=transient,
        ) from exc
    except RuntimeError as exc:
        raise GitHubReadOnlyAdapterError(str(exc)) from exc

