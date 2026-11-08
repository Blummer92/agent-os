"""Fixed, owner-triggered remote start of the existing Agent OS Codespace.

This is a narrow lifecycle caller, not a general Codespaces administrator.
No credentials, target names, commands, or arbitrary operations come from the
comment body. The workflow owns one-attempt admission and serialization.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Callable

from .codespaces_lifecycle import _api, _ssh_ready, _state
from .dev_validation import REPOSITORY
from .dev_validation_codespaces import (
    APPROVED_OWNER, MAX_LISTED_CODESPACES, _CODESPACE_NAME_RE,
)
from .github_issue_comment_ingress import (
    CODESPACE_START_ISSUE, CODESPACE_START_TRIGGER,
)

_RUN = Callable[..., subprocess.CompletedProcess[str]]
_ALLOWED_STATES = frozenset({"Shutdown", "Available"})


def _receipt(status: str, reason: str, *, name: str | None = None,
             pre_state: str | None = None, post_state: str | None = None,
             start_issued: bool = False, ssh_ready: bool = False,
             comment_id: int | None = None, run_id: int | None = None) -> dict[str, object]:
    return {
        "schema_version": "1.0", "status": status, "reason_codes": [reason],
        "repository": REPOSITORY, "issue_number": CODESPACE_START_ISSUE,
        "operation": "codespace-start", "comment_id": comment_id,
        "workflow_run_id": run_id, "codespace_name": name,
        "execution_surface_id": f"codespace:{name}" if name else None,
        "pre_state": pre_state, "post_state": post_state,
        "start_issued": start_issued, "ssh_ready": ssh_ready,
        "lifecycle_authorized": status != "blocked",
        "github_repository_writes_authorized": False,
        "execution_authorized": False, "stop_issued": False,
        "create_delete_rebuild_authorized": False,
    }


def _list_target(run: _RUN, read_token: str) -> tuple[str | None, str | None, str]:
    """Qualify exactly one owner/repository Codespace, including Shutdown."""
    result = _api(run, "GET", f"/repos/{REPOSITORY}/codespaces?per_page={MAX_LISTED_CODESPACES}", read_token)
    if result.returncode != 0:
        return None, None, "codespaces-discovery-unavailable"
    try:
        payload = json.loads(result.stdout)
    except (TypeError, ValueError):
        return None, None, "codespaces-discovery-invalid"
    if type(payload) is not dict or type(payload.get("codespaces")) is not list or type(payload.get("total_count")) is not int or payload["total_count"] != len(payload["codespaces"]):
        return None, None, "codespaces-discovery-invalid"
    candidates = []
    for item in payload["codespaces"]:
        if type(item) is not dict:
            return None, None, "codespaces-discovery-invalid"
        owner, repository = item.get("owner"), item.get("repository")
        name, state = item.get("name"), item.get("state")
        if (type(owner) is dict and owner.get("login") == APPROVED_OWNER
            and type(repository) is dict and repository.get("full_name") == REPOSITORY):
            if type(name) is not str or _CODESPACE_NAME_RE.fullmatch(name) is None or type(state) is not str:
                return None, None, "codespaces-discovery-invalid"
            candidates.append((name, state))
    if len(candidates) != 1:
        return None, None, "codespaces-target-ambiguous-or-missing"
    name, state = candidates[0]
    if state not in _ALLOWED_STATES:
        return name, state, "codespaces-state-not-qualified"
    return name, state, "qualified"


def run_fixed_start(*, transport: dict[str, object], read_token: str,
                    lifecycle_token: str, run: _RUN, sleep: Callable[[float], None] = time.sleep,
                    wait_attempts: int = 12) -> dict[str, object]:
    """One bounded start request, never a stop or arbitrary command.

    Caller MUST serialize the workflow and prohibit reruns. A second independent
    owner comment is an independent explicit request; an already Available
    Codespace is verified without a second start.
    """
    comment_id = transport.get("comment_id")
    if not (transport.get("status") == "accepted"
            and transport.get("reason") == "accepted-codespace-start-envelope"
            and transport.get("repository") == REPOSITORY
            and transport.get("issue_number") == CODESPACE_START_ISSUE
            and transport.get("actor") == APPROVED_OWNER
            and transport.get("run_attempt") == 1
            and type(comment_id) is int and comment_id > 0
            and type(read_token) is str and bool(read_token)
            and type(lifecycle_token) is str and bool(lifecycle_token)
            and read_token != lifecycle_token
            and type(wait_attempts) is int and 1 <= wait_attempts <= 24):
        return _receipt("blocked", "start-authorization-or-credential-unavailable")
    run_id = os.environ.get("GITHUB_RUN_ID")
    parsed_run_id = int(run_id) if type(run_id) is str and run_id.isdigit() else None
    try:
        name, observed, reason = _list_target(run, read_token)
    except (OSError, subprocess.TimeoutExpired):
        return _receipt("blocked", "codespaces-discovery-error", comment_id=comment_id, run_id=parsed_run_id)
    if reason != "qualified":
        return _receipt("blocked", reason, name=name, pre_state=observed, comment_id=comment_id, run_id=parsed_run_id)
    started = False
    try:
        # Independent user-token readback before mutation; no stale target.
        pre_state = _state(run, name, lifecycle_token)
        if pre_state != observed or pre_state not in _ALLOWED_STATES:
            return _receipt("blocked", "codespaces-prestate-mismatch", name=name, pre_state=pre_state, comment_id=comment_id, run_id=parsed_run_id)
        if pre_state == "Shutdown":
            # Recheck with the read credential immediately before POST.
            name_again, state_again, reason_again = _list_target(run, read_token)
            if reason_again != "qualified" or name_again != name or state_again != "Shutdown":
                return _receipt("blocked", "codespaces-target-drift", name=name, pre_state=pre_state, comment_id=comment_id, run_id=parsed_run_id)
            started = True  # attempted, not proof the provider accepted it
            response = _api(run, "POST", f"/user/codespaces/{name}/start", lifecycle_token)
            if response.returncode != 0:
                return _receipt("needs-decision", "codespaces-start-outcome-uncertain", name=name, pre_state=pre_state, start_issued=True, comment_id=comment_id, run_id=parsed_run_id)
        for attempt in range(wait_attempts):
            current = _state(run, name, lifecycle_token)
            if current == "Available" and _ssh_ready(run, name, read_token):
                return _receipt("success", "codespaces-ssh-ready", name=name, pre_state=pre_state, post_state=current, start_issued=started, ssh_ready=True, comment_id=comment_id, run_id=parsed_run_id)
            if attempt + 1 < wait_attempts:
                sleep(5)
        return _receipt("needs-decision", "codespaces-ssh-readiness-unverified", name=name, pre_state=pre_state, post_state=current, start_issued=started, comment_id=comment_id, run_id=parsed_run_id)
    except (OSError, subprocess.TimeoutExpired):
        return _receipt("needs-decision", "codespaces-start-outcome-uncertain", name=name, pre_state=observed, start_issued=started, comment_id=comment_id, run_id=parsed_run_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.transport.read_text(encoding="utf-8"))
        if type(payload) is not dict:
            raise ValueError("invalid transport")
        result = run_fixed_start(
            transport=payload,
            read_token=os.environ.get("AGENT_OS_CODESPACES_READ_TOKEN", ""),
            lifecycle_token=os.environ.get("AGENT_OS_CODESPACES_LIFECYCLE_TOKEN", ""),
            run=lambda cmd, **kw: subprocess.run(cmd, capture_output=True, text=True, check=False, **kw),
        )
    except (OSError, ValueError, TypeError):
        result = _receipt("blocked", "codespaces-start-input-invalid")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in {"codespace_name"}}))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
