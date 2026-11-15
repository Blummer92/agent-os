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
    admit_issue_comment_event,
)

_RUN = Callable[..., subprocess.CompletedProcess[str]]
_ALLOWED_STATES = frozenset({"Shutdown", "Available"})
_RUN_ID_RE = re.compile(r"[0-9]{1,20}", re.ASCII)
_APPROVED_OWNER_ID = 32861845


def _matches_trusted_event(transport: dict[str, object], event: object,
                           run_attempt: int) -> bool:
    """Re-derive admission from the runner's event, not the transport JSON.

    The logical ID is deterministic and not a signature. Validating its value
    alone cannot authenticate a comment; the GitHub-supplied event must agree
    with the entire parsed transport before any lifecycle API call.
    """
    if type(event) is not dict or type(run_attempt) is not int or run_attempt != 1:
        return False
    comment, sender = event.get("comment"), event.get("sender")
    if type(comment) is not dict or type(sender) is not dict:
        return False
    author = comment.get("user")
    if (type(author) is not dict
            or type(author.get("id")) is not int or author["id"] != _APPROVED_OWNER_ID
            or type(sender.get("id")) is not int or sender["id"] != _APPROVED_OWNER_ID):
        return False
    try:
        expected = admit_issue_comment_event(
            event, expected_repository=REPOSITORY,
            allowed_actor=APPROVED_OWNER, run_attempt=run_attempt,
        )
    except (TypeError, ValueError):
        return False
    return (expected.status == "accepted"
            and expected.reason == "accepted-codespace-start-envelope"
            and expected.to_dict() == transport)


def _receipt(status: str, reason: str, *, name: str | None = None,
             pre_state: str | None = None, post_state: str | None = None,
             start_issued: bool = False, ssh_ready: bool = False,
             comment_id: int | None = None, run_id: int | None = None,
             lifecycle_authorized: bool = False) -> dict[str, object]:
    # lifecycle_authorized is explicit evidence, not derived from status: it is
    # True only once every owner, credential, target and pre-state check passed
    # for this exact target and the adapter proceeded to start or verify.
    return {
        "schema_version": "1.0", "status": status, "reason_codes": [reason],
        "repository": REPOSITORY, "issue_number": CODESPACE_START_ISSUE,
        "operation": "codespace-start", "comment_id": comment_id,
        "workflow_run_id": run_id, "codespace_name": name,
        "execution_surface_id": f"codespace:{name}" if name else None,
        "pre_state": pre_state, "post_state": post_state,
        "start_issued": start_issued, "ssh_ready": ssh_ready,
        "lifecycle_authorized": lifecycle_authorized,
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
                    lifecycle_token: str, run: _RUN, trusted_event: object,
                    trusted_run_attempt: int,
                    sleep: Callable[[float], None] = time.sleep,
                    wait_attempts: int = 12) -> dict[str, object]:
    """One bounded start request, never a stop or arbitrary command.

    Caller MUST serialize the workflow and prohibit reruns. A second independent
    owner comment is an independent explicit request; an already Available
    Codespace is verified without a second start.
    """
    comment_id = transport.get("comment_id")
    issue_number = transport.get("issue_number")
    run_attempt = transport.get("run_attempt")
    # Exact int types: bool and float (True, 1.0, 3345.0) must not satisfy ==.
    if not (transport.get("status") == "accepted"
            and transport.get("reason") == "accepted-codespace-start-envelope"
            and transport.get("repository") == REPOSITORY
            and type(issue_number) is int and issue_number == CODESPACE_START_ISSUE
            and transport.get("actor") == APPROVED_OWNER
            and type(run_attempt) is int and run_attempt == 1
            and type(comment_id) is int and comment_id > 0
            and type(read_token) is str and bool(read_token)
            and type(lifecycle_token) is str and bool(lifecycle_token)
            and read_token != lifecycle_token
            and type(wait_attempts) is int and 1 <= wait_attempts <= 24
            and _matches_trusted_event(transport, trusted_event, trusted_run_attempt)):
        return _receipt("blocked", "start-authorization-or-credential-unavailable")
    run_id = os.environ.get("GITHUB_RUN_ID")
    parsed_run_id = int(run_id) if type(run_id) is str and _RUN_ID_RE.fullmatch(run_id) else None
    try:
        name, observed, reason = _list_target(run, read_token)
    except Exception:
        # No lifecycle request has been sent yet, so nothing can have changed.
        return _receipt("blocked", "codespaces-discovery-error", comment_id=comment_id, run_id=parsed_run_id)
    if reason != "qualified":
        return _receipt("blocked", reason, name=name, pre_state=observed, comment_id=comment_id, run_id=parsed_run_id)
    if name is None:
        # Explicit fail-closed narrowing: a qualified result always names its target.
        return _receipt("blocked", "codespaces-discovery-invalid", comment_id=comment_id, run_id=parsed_run_id)
    started = False
    admitted = False
    try:
        # Independent user-token readback before mutation; no stale target.
        pre_state = _state(run, name, lifecycle_token)
        if pre_state is None:
            # No independent pre-state was readable: it is not a mismatch.
            return _receipt("blocked", "codespaces-precheck-error", name=name, comment_id=comment_id, run_id=parsed_run_id)
        if pre_state != observed or pre_state not in _ALLOWED_STATES:
            return _receipt("blocked", "codespaces-prestate-mismatch", name=name, pre_state=pre_state, comment_id=comment_id, run_id=parsed_run_id)
        if pre_state == "Shutdown":
            # Recheck with the read credential immediately before POST.
            name_again, state_again, reason_again = _list_target(run, read_token)
            if reason_again != "qualified" or name_again != name or state_again != "Shutdown":
                return _receipt("blocked", "codespaces-target-drift", name=name, pre_state=pre_state, comment_id=comment_id, run_id=parsed_run_id)
        admitted = True  # every pre-mutation check passed for this exact target
        if pre_state == "Shutdown":
            started = True  # attempted, not proof the provider accepted it
            response = _api(run, "POST", f"/user/codespaces/{name}/start", lifecycle_token)
            if response.returncode != 0:
                return _receipt("needs-decision", "codespaces-start-outcome-uncertain", name=name, pre_state=pre_state, start_issued=True, comment_id=comment_id, run_id=parsed_run_id, lifecycle_authorized=True)
        current: str | None = None
        for attempt in range(wait_attempts):
            current = _state(run, name, lifecycle_token)
            if current == "Available" and _ssh_ready(run, name, read_token):
                return _receipt("success", "codespaces-ssh-ready", name=name, pre_state=pre_state, post_state=current, start_issued=started, ssh_ready=True, comment_id=comment_id, run_id=parsed_run_id, lifecycle_authorized=True)
            if attempt + 1 < wait_attempts:
                sleep(5)
        return _receipt("needs-decision", "codespaces-ssh-readiness-unverified", name=name, pre_state=pre_state, post_state=current, start_issued=started, comment_id=comment_id, run_id=parsed_run_id, lifecycle_authorized=True)
    except Exception:
        # Any failure after a start request may have been sent is uncertain,
        # never "nothing happened", and is never retried here. Before that
        # point no lifecycle mutation was requested, so the outcome is certain.
        if started:
            return _receipt("needs-decision", "codespaces-start-outcome-uncertain", name=name, pre_state=observed, start_issued=True, comment_id=comment_id, run_id=parsed_run_id, lifecycle_authorized=True)
        if admitted:
            return _receipt("needs-decision", "codespaces-ssh-readiness-unverified", name=name, pre_state=observed, comment_id=comment_id, run_id=parsed_run_id, lifecycle_authorized=True)
        return _receipt("blocked", "codespaces-precheck-error", name=name, pre_state=observed, comment_id=comment_id, run_id=parsed_run_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    # Only transport parsing may yield "input-invalid": once run_fixed_start
    # begins, it alone records the outcome (it handles its own failures).
    try:
        payload = json.loads(args.transport.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    if type(payload) is not dict:
        result = _receipt("blocked", "codespaces-start-input-invalid")
    else:
        # GITHUB_EVENT_PATH is runner-provided event evidence. A copied or
        # locally forged transport file alone does not authorize mutation.
        event: object = None
        event_path = os.environ.get("GITHUB_EVENT_PATH", "")
        try:
            if event_path:
                event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass  # missing/malformed event fails closed inside run_fixed_start
        attempt_text = os.environ.get("GITHUB_RUN_ATTEMPT", "")
        trusted_attempt = int(attempt_text) if _RUN_ID_RE.fullmatch(attempt_text) else 0
        result = run_fixed_start(
            transport=payload, trusted_event=event,
            trusted_run_attempt=trusted_attempt,
            read_token=os.environ.get("AGENT_OS_CODESPACES_READ_TOKEN", ""),
            lifecycle_token=os.environ.get("AGENT_OS_CODESPACES_LIFECYCLE_TOKEN", ""),
            run=lambda cmd, **kw: subprocess.run(cmd, capture_output=True, text=True, check=False, **kw),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    # The log line matches the uploaded receipt: the Codespace name is already
    # published through the artifact and the existing execution_surface_id
    # evidence, so a partial stdout filter would only imply false redaction.
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
