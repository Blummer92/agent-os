"""Target-bound Codespaces lifecycle contract for #3345.

Repository logic only. Lifecycle and transport credentials are injected by a
separately authorized caller; this module never provisions, stores, rotates, or
broadens credentials. Target discovery is delegated to the canonical #2965
resolver and one-shot authorization consumption is delegated to the existing
authorization owner rather than introducing a second state store.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from .dev_validation import REPOSITORY
from .dev_validation_codespaces import (
    APPROVED_CODESPACE_PROFILE_ID,
    APPROVED_OWNER,
    CodespaceSelection,
    resolve_current_codespace,
)

_CODESPACE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,99}$", re.ASCII)
_GITHUB_TOKEN_ENV_KEYS = ("GH_TOKEN", "GITHUB_TOKEN")
Run =Callable[..., subprocess.CompletedProcess[str]]
Sleep = Callable[[float], None]
Resolve = Callable[[], CodespaceSelection]


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
    codespaces_profile_id: str
    authorization_reference: str
    authorization_consumed: bool
    operation_id: str
    pre_state: str
    start_issued: bool
    ssh_ready: bool
    stop_issued: bool
    cleanup_complete: bool
    final_state: str | None
    lifecycle_permission: str = "codespaces_lifecycle_admin:write"
    external_writes_authorized: bool = False
    repository_writes_authorized: bool = False


def _credential_env(token: str) -> dict[str, str]:
    """Inherit the parent environment, replacing only GitHub credentials.

    PATH, HOME, proxy, and CA settings must survive: a credential-injecting
    proxy is bypassed when they are dropped (#3345 HTTP 401). Inherited
    GitHub token variables are removed so they cannot override the selected
    credential.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _GITHUB_TOKEN_ENV_KEYS
    }
    env["GH_TOKEN"] = token
    return env


def _api(
    run: Run, method: str, endpoint: str, token: str
) -> subprocess.CompletedProcess[str]:
    return run(
        (
            "gh",
            "api",
            "--method",
            method,
            "-H",
            "Accept: application/vnd.github+json",
            endpoint,
        ),
        timeout=30,
        env=_credential_env(token),
    )


def _state(run: Run, name: str, token: str) -> str | None:
    result = _api(run, "GET", f"/user/codespaces/{name}", token)
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if (
        type(payload) is not dict
        or payload.get("name") != name
        or type(payload.get("owner")) is not dict
        or payload["owner"].get("login") != APPROVED_OWNER
        or type(payload.get("repository")) is not dict
        or payload["repository"].get("full_name") != REPOSITORY
    ):
        return None
    state = payload.get("state")
    return state if type(state) is str else None


def _ssh_ready(run: Run, name: str, transport_token: str) -> bool:
    result = run(
        ("gh", "codespace", "ssh", "-c", name, "--", "true"),
        timeout=30,
        env=_credential_env(transport_token),
    )
    return result.returncode == 0


def run_authorized_lifecycle(
    authorization: LifecycleAuthorization,
    *,
    lifecycle_token: str,
    transport_token: str,
    run: Run,
    operation: Callable[[str], bool],
    consume_authorization: Callable[[LifecycleAuthorization], bool],
    resolve_codespace: Resolve = resolve_current_codespace,
    sleep: Sleep = time.sleep,
    wait_attempts: int = 12,
) -> LifecycleEvidence:
    """Run one bound start/readiness/operation/stop lifecycle.

    The lifecycle token is used only for authenticated-user lifecycle API
    calls. The weaker transport token is used for SSH readiness. The registered
    operation callback receives only the already-bound Codespace name and never
    either credential.
    """
    if (
        authorization.repository != REPOSITORY
        or not authorization.one_shot
        or authorization.final_state != "Shutdown"
        or not authorization.authorization_reference
        or not authorization.operation_id
        or _CODESPACE_NAME_RE.fullmatch(authorization.codespace_name) is None
        or not lifecycle_token
        or not transport_token
        or lifecycle_token == transport_token
        or type(wait_attempts) is not int
        or wait_attempts < 1
        or wait_attempts > 120
    ):
        raise ValueError("invalid bounded lifecycle authorization")

    resolved = resolve_codespace()
    if (
        type(resolved) is not CodespaceSelection
        or resolved.codespace_name is None
        or resolved.codespace_name != authorization.codespace_name
        or resolved.state not in {"Shutdown", "Available"}
    ):
        return _evidence(
            authorization,
            pre_state=resolved.state if type(resolved) is CodespaceSelection and resolved.state else "unavailable",
            authorization_consumed=False,
            start_issued=False,
            ssh_ready=False,
            stop_issued=False,
            cleanup_complete=False,
            final_state=None,
            status="needs-decision",
            reason="codespace-canonical-target-mismatch",
        )

    name = resolved.codespace_name
    pre_state = _state(run, name, lifecycle_token)
    if pre_state not in {"Shutdown", "Available"}:
        return _evidence(
            authorization,
            pre_state=pre_state or "unavailable",
            authorization_consumed=False,
            start_issued=False,
            ssh_ready=False,
            stop_issued=False,
            cleanup_complete=False,
            final_state=None,
            status="needs-decision",
            reason="codespace-prestate-invalid",
        )

    if not consume_authorization(authorization):
        return _evidence(
            authorization,
            pre_state=pre_state,
            authorization_consumed=False,
            start_issued=False,
            ssh_ready=False,
            stop_issued=False,
            cleanup_complete=False,
            final_state=pre_state,
            status="needs-decision",
            reason="codespace-authorization-replay-blocked",
        )

    start_issued = False
    stop_issued = False
    ssh_ready = False
    cleanup_complete = False
    final_state: str | None = None
    status, reason = "needs-decision", "codespace-lifecycle-failed"
    may_execute = pre_state == "Available"

    try:
        if pre_state == "Shutdown":
            start_issued = True
            started = _api(
                run, "POST", f"/user/codespaces/{name}/start", lifecycle_token
            )
            if started.returncode == 0:
                may_execute = True
            else:
                status, reason = "needs-decision", "codespace-start-failed"

        if may_execute:
            for _ in range(wait_attempts):
                if _state(run, name, lifecycle_token) == "Available" and _ssh_ready(
                    run, name, transport_token
                ):
                    ssh_ready = True
                    break
                sleep(5)

            if not ssh_ready:
                status, reason = "needs-decision", "codespace-ssh-not-ready"
            elif operation(name):
                status, reason = "success", "operation-complete"
            else:
                status, reason = "failure", "operation-failed"
    finally:
        stop_issued = True
        _api(run, "POST", f"/user/codespaces/{name}/stop", lifecycle_token)
        for _ in range(wait_attempts):
            final_state = _state(run, name, lifecycle_token)
            if final_state == "Shutdown":
                cleanup_complete = True
                break
            sleep(5)
        if not cleanup_complete:
            status, reason = "needs-decision", "codespace-cleanup-failed"

    return _evidence(
        authorization,
        pre_state=pre_state,
        authorization_consumed=True,
        start_issued=start_issued,
        ssh_ready=ssh_ready,
        stop_issued=stop_issued,
        cleanup_complete=cleanup_complete,
        final_state=final_state,
        status=status,
        reason=reason,
    )


def _evidence(
    auth: LifecycleAuthorization,
    *,
    pre_state: str,
    authorization_consumed: bool,
    start_issued: bool,
    ssh_ready: bool,
    stop_issued: bool,
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
        codespaces_profile_id=APPROVED_CODESPACE_PROFILE_ID,
        authorization_reference=auth.authorization_reference,
        authorization_consumed=authorization_consumed,
        operation_id=auth.operation_id,
        pre_state=pre_state,
        start_issued=start_issued,
        ssh_ready=ssh_ready,
        stop_issued=stop_issued,
        cleanup_complete=cleanup_complete,
        final_state=final_state,
    )
