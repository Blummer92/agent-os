"""Target-bound Codespaces lifecycle contract for #3345.

Repository logic only. The lifecycle credential is injected by a separately
authorized caller; this module never provisions, stores, or broadens credentials.
"""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from .dev_validation import REPOSITORY
from .dev_validation_codespaces import APPROVED_CODESPACE_PROFILE_ID, APPROVED_OWNER

_CODESPACE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,99}$", re.ASCII)
Run = Callable[..., subprocess.CompletedProcess[str]]
Sleep = Callable[[float], None]


@dataclass(frozen=True)
class LifecycleAuthorization:
    repository: str
    codespace_name: str
    authorization_reference: str
    operation_id: str
    final_state: str = "Shutdown"
    one_shot: bool = True


@dataclass(frozen=True)
class LifecycleEvidence:
    status: str
    reason: str
    repository: str
    codespace_name: str
    execution_surface_id: str
    authorization_reference: str
    operation_id: str
    pre_state: str
    ssh_ready: bool
    cleanup_complete: bool
    final_state: str | None
    lifecycle_permission: str = "codespaces_lifecycle_admin:write"
    external_writes_authorized: bool = False
    repository_writes_authorized: bool = False


def _api(run: Run, method: str, endpoint: str, token: str) -> subprocess.CompletedProcess[str]:
    return run(
        ("gh", "api", "--method", method, "-H", "Accept: application/vnd.github+json", endpoint),
        timeout=30,
        env={"GH_TOKEN": token},
    )


def _state(run: Run, name: str, token: str) -> str | None:
    result = _api(run, "GET", f"/user/codespaces/{name}", token)
    if result.returncode != 0:
        return None
    import json
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if (
        type(payload) is not dict
        or payload.get("name") != name
        or payload.get("owner", {}).get("login") != APPROVED_OWNER
        or payload.get("repository", {}).get("full_name") != REPOSITORY
    ):
        return None
    state = payload.get("state")
    return state if type(state) is str else None


def run_authorized_lifecycle(
    authorization: LifecycleAuthorization,
    *,
    lifecycle_token: str,
    run: Run,
    operation: Callable[[str], bool],
    sleep: Sleep = time.sleep,
    wait_attempts: int = 12,
) -> LifecycleEvidence:
    """Start the bound surface, prove SSH readiness, run one operation, stop it."""
    if (
        authorization.repository != REPOSITORY
        or not authorization.one_shot
        or authorization.final_state != "Shutdown"
        or not authorization.authorization_reference
        or not authorization.operation_id
        or _CODESPACE_NAME_RE.fullmatch(authorization.codespace_name) is None
        or not lifecycle_token
    ):
        raise ValueError("invalid bounded lifecycle authorization")

    name = authorization.codespace_name
    pre_state = _state(run, name, lifecycle_token)
    if pre_state not in {"Shutdown", "Available"}:
        return _evidence(authorization, pre_state or "unavailable", False, False, None, "needs-decision", "codespace-prestate-invalid")

    cleanup_complete = False
    final_state: str | None = None
    ssh_ready = False
    status, reason = "needs-decision", "codespace-lifecycle-failed"
    try:
        if pre_state == "Shutdown":
            started = _api(run, "POST", f"/user/codespaces/{name}/start", lifecycle_token)
            if started.returncode != 0:
                return _evidence(authorization, pre_state, False, False, None, "needs-decision", "codespace-start-failed")
        for _ in range(wait_attempts):
            if _state(run, name, lifecycle_token) == "Available":
                probe = run(
                    ("gh", "codespace", "ssh", "-c", name, "--", "true"),
                    timeout=30,
                    env={"GH_TOKEN": lifecycle_token},
                )
                if probe.returncode == 0:
                    ssh_ready = True
                    break
            sleep(5)
        if not ssh_ready:
            reason = "codespace-ssh-not-ready"
        elif operation(name):
            status, reason = "success", "operation-complete"
        else:
            status, reason = "failure", "operation-failed"
    finally:
        stopped = _api(run, "POST", f"/user/codespaces/{name}/stop", lifecycle_token)
        if stopped.returncode == 0:
            for _ in range(wait_attempts):
                final_state = _state(run, name, lifecycle_token)
                if final_state == "Shutdown":
                    cleanup_complete = True
                    break
                sleep(5)
        if not cleanup_complete:
            status, reason = "needs-decision", "codespace-cleanup-failed"
    return _evidence(authorization, pre_state, ssh_ready, cleanup_complete, final_state, status, reason)


def _evidence(
    auth: LifecycleAuthorization,
    pre_state: str,
    ssh_ready: bool,
    cleanup_complete: bool,
    final_state: str | None,
    status: str,
    reason: str,
) -> LifecycleEvidence:
    return LifecycleEvidence(
        status=status,
        reason=reason,
        repository=auth.repository,
        codespace_name=auth.codespace_name,
        execution_surface_id=f"codespace:{auth.codespace_name}",
        authorization_reference=auth.authorization_reference,
        operation_id=auth.operation_id,
        pre_state=pre_state,
        ssh_ready=ssh_ready,
        cleanup_complete=cleanup_complete,
        final_state=final_state,
    )
