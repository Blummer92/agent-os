"""Bounded read-only Codespaces discovery transport for #2931.

This provider adapter consumes only the accepted discovery envelope admitted
by the canonical issue-comment ingress. It runs the checked-in handoff
discovery implementation on the one current Codespace resolved from live
GitHub evidence (#2965), via the already-approved Codespaces SSH transport.

It never starts, stops, edits, creates, deletes, or exports a Codespace, and
discovery itself performs no Scheduler dispatch, GitHub write, handoff
generation, store mutation, or execution authorization. No Codespace identity
is compiled into this module.

A missing credential, unresolvable Codespace, missing repository checkout,
missing discovery implementation, missing checkpoint store, or malformed
evidence fails closed. A Codespace without the host-local checkpoint store
reports codespaces_capable=False so the workflow falls back through the
existing governed GCE path instead of returning a misleading not-found.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .dev_validation_codespaces import (
    APPROVED_CODESPACE_PROFILE_ID,
    _CODESPACE_NAME_RE,
    _bounded_text,
    resolve_current_codespace,
    surface_id,
)
from .dev_validation_codespaces import Run, _run
from .github_issue_comment_ingress import IssueCommentIngressResult

REPOSITORY = "Blummer92/agent-os"
_FRAME_START = "===AGENT-OS-CODESPACES-DISCOVERY-JSON-BEGIN==="
_FRAME_END = "===AGENT-OS-CODESPACES-DISCOVERY-JSON-END==="
MAX_RESULT_LOG_CHARS = 4096
_REMOTE_MAX_BOUNDED_SECONDS = 120
_TRANSPORT_OVERHEAD_SECONDS = 60
_RUN_TIMEOUT_SECONDS = _REMOTE_MAX_BOUNDED_SECONDS + _TRANSPORT_OVERHEAD_SECONDS

# The remote runner locates the repository checkout on the Codespace from a
# fixed candidate list and verifies the discovery implementation exists before
# importing it. No caller-provided path is accepted.
_REMOTE_DISCOVERY_SOURCE = r'''import json,os,subprocess,sys
from pathlib import Path
REPOSITORY="Blummer92/agent-os"
FRAME_START="===AGENT-OS-CODESPACES-DISCOVERY-JSON-BEGIN==="
FRAME_END="===AGENT-OS-CODESPACES-DISCOVERY-JSON-END==="
DISCOVERY_REL=Path("scripts")/"agent_os_execution_checkpoint"/"handoff_discovery.py"
def _repo_candidates():
    cands=[Path("/workspaces/agent-os"),Path.home()/"agent-os"]
    try:
        top=subprocess.run(["git","rev-parse","--show-toplevel"],capture_output=True,text=True,timeout=15)
        if top.returncode==0 and top.stdout.strip():
            cands.insert(0,Path(top.stdout.strip()))
    except Exception:
        pass
    return cands
def _emit(payload):
    sys.stdout.write(FRAME_START+json.dumps(payload,sort_keys=True,separators=(",",":"))+FRAME_END)
    sys.stdout.flush()
def _base(repository,issue_number,codespace_name):
    return {"schema_version":"1.0","status":"needs-decision","reason_codes":[],"repository":repository,"issue_number":issue_number,"matching_descriptor_count":0,"handoff_id":None,"result_id":None,"execution_authorized":False,"scheduler_invoked":False,"side_effects_performed":False,"codespaces_profile_id":"agent-os-codespaces-v1","execution_surface_id":("codespace:"+codespace_name if codespace_name else None)}
def main():
    if len(sys.argv)!=4:
        _emit({"schema_version":"1.0","status":"needs-decision","reason_codes":["codespaces-discovery-argv-malformed"],"repository":REPOSITORY,"issue_number":0,"matching_descriptor_count":0,"handoff_id":None,"result_id":None,"execution_authorized":False,"scheduler_invoked":False,"side_effects_performed":False,"codespaces_profile_id":"agent-os-codespaces-v1","execution_surface_id":None})
        return
    repository,issue_raw,codespace_name=sys.argv[1],sys.argv[2],sys.argv[3]
    try:
        issue_number=int(issue_raw)
    except ValueError:
        issue_number=0
    base=_base(repository,issue_number,codespace_name)
    if repository!=REPOSITORY or issue_number<1:
        base["reason_codes"]=["codespaces-discovery-identity-rejected"]
        _emit(base)
        return
    repo=None
    for cand in _repo_candidates():
        try:
            if (cand/DISCOVERY_REL).is_file():
                repo=cand
                break
        except OSError:
            continue
    if repo is None:
        base["reason_codes"]=["codespaces-discovery-repo-unavailable"]
        _emit(base)
        return
    sys.path.insert(0,str(repo/"scripts"))
    try:
        from agent_os_execution_checkpoint.handoff_discovery import discover_issue_handoff
    except Exception:
        base["reason_codes"]=["codespaces-discovery-import-failed"]
        _emit(base)
        return
    store_root=os.environ.get("AGENT_OS_CHECKPOINT_STORE_ROOT","/var/lib/agent-os/checkpoints")
    if not (Path(store_root)/"invocations").is_dir():
        base["reason_codes"]=["codespaces-discovery-store-unavailable"]
        _emit(base)
        return
    try:
        result=discover_issue_handoff(store_root,repository=repository,issue_number=issue_number)
    except Exception:
        base["reason_codes"]=["codespaces-discovery-store-failed"]
        _emit(base)
        return
    payload=dict(base)
    payload.update({
        "status":result.status.value,
        "reason_codes":[item.value for item in result.reason_codes],
        "matching_descriptor_count":result.matching_descriptor_count,
        "handoff_id":result.handoff_id,
        "result_id":result.result_id,
    })
    _emit(payload)
main()
'''


def _extract_framed_payload(stdout: object) -> str | None:
    if (
        type(stdout) is not str
        or stdout.count(_FRAME_START) != 1
        or stdout.count(_FRAME_END) != 1
    ):
        return None
    start = stdout.find(_FRAME_START)
    end = stdout.find(_FRAME_END)
    return (
        stdout[start + len(_FRAME_START) : end].strip()
        if start >= 0 and end > start
        else None
    )


@dataclass(frozen=True)
class DiscoveryRequest:
    repository: str
    issue_number: int


def _request_from_ingress(ingress: IssueCommentIngressResult) -> DiscoveryRequest:
    if ingress.status != "accepted" or ingress.reason != "accepted-discovery-envelope":
        raise ValueError("codespaces discovery requires the accepted discovery envelope")
    if ingress.run_attempt != 1:
        raise ValueError("workflow reruns cannot perform discovery")
    if ingress.handoff_id_or_none is not None:
        raise ValueError("discovery must not carry a handoff identity")
    if ingress.repository != REPOSITORY or ingress.issue_number is None:
        raise ValueError("discovery ingress identity incomplete")
    return DiscoveryRequest(repository=ingress.repository, issue_number=ingress.issue_number)


def _route(
    selected: bool,
    reason: str,
    *,
    codespace_name: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "selected": selected,
        "reason_codes": [reason],
        "codespace_name": codespace_name,
        "codespaces_profile_id": APPROVED_CODESPACE_PROFILE_ID,
        "execution_surface_id": surface_id(codespace_name),
        "repository": REPOSITORY,
        "credential_permission": "codespaces:read",
        "lifecycle_mutation_authorized": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "external_writes_authorized": False,
        "side_effects_performed": False,
    }


def _failure(
    request: DiscoveryRequest, reason: str, codespace_name: str | None = None
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": "needs-decision",
        "reason_codes": [reason],
        "repository": request.repository,
        "issue_number": request.issue_number,
        "matching_descriptor_count": 0,
        "handoff_id": None,
        "result_id": None,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "side_effects_performed": False,
        "codespaces_profile_id": APPROVED_CODESPACE_PROFILE_ID,
        "execution_surface_id": surface_id(codespace_name),
    }


def select_codespaces_discovery(
    ingress: IssueCommentIngressResult,
    *,
    run: Run = _run,
) -> tuple[dict[str, object], DiscoveryRequest | None]:
    """Decide whether the discovery envelope can consume the Codespaces path."""
    if ingress.status != "accepted" or ingress.reason != "accepted-discovery-envelope":
        return _route(False, "not-discovery-envelope"), None
    request = _request_from_ingress(ingress)
    selection = resolve_current_codespace(run)
    return (
        _route(
            selection.selected,
            selection.reason,
            codespace_name=selection.codespace_name,
        ),
        request,
    )


def run_discovery_over_codespaces(
    request: DiscoveryRequest,
    *,
    codespace_name: str,
    run: Run = _run,
) -> dict[str, object]:
    """Run bounded read-only discovery on the selected Codespace."""
    if type(codespace_name) is not str or _CODESPACE_NAME_RE.fullmatch(codespace_name) is None:
        raise ValueError("a resolved current Codespace name is required")
    try:
        completed = run(
            (
                "gh",
                "codespace",
                "ssh",
                "-c",
                codespace_name,
                "--",
                "python3",
                "-c",
                _REMOTE_DISCOVERY_SOURCE,
                request.repository,
                str(request.issue_number),
                codespace_name,
            ),
            timeout=_RUN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        evidence = _failure(request, "discovery-codespaces-transport-timeout", codespace_name)
        stdout_tail, stdout_truncated = _bounded_text(exc.stdout)
        stderr_tail, stderr_truncated = _bounded_text(exc.stderr)
        evidence.update(
            {
                "ssh_stdout_tail": stdout_tail,
                "ssh_stdout_truncated": stdout_truncated,
                "ssh_stderr_tail": stderr_tail,
                "ssh_stderr_truncated": stderr_truncated,
                "transport_timeout_seconds": _RUN_TIMEOUT_SECONDS,
            }
        )
        return {"discovery": evidence, "codespaces_capable": False}
    if completed.returncode != 0:
        evidence = _failure(request, "discovery-codespaces-ssh-failed", codespace_name)
        tail, truncated = _bounded_text(completed.stderr)
        evidence.update(
            {
                "ssh_exit_code": completed.returncode,
                "ssh_stderr_tail": tail,
                "ssh_stderr_truncated": truncated,
            }
        )
        return {"discovery": evidence, "codespaces_capable": False}
    framed = _extract_framed_payload(completed.stdout)
    if framed is None:
        return {"discovery": _failure(request, "discovery-codespaces-frame-invalid", codespace_name), "codespaces_capable": False}
    try:
        payload = json.loads(framed)
    except json.JSONDecodeError:
        return {"discovery": _failure(request, "discovery-codespaces-evidence-not-json", codespace_name), "codespaces_capable": False}
    if type(payload) is not dict:
        return {"discovery": _failure(request, "discovery-codespaces-evidence-malformed", codespace_name), "codespaces_capable": False}
    if payload.get("repository") != request.repository or payload.get("issue_number") != request.issue_number:
        return {"discovery": _failure(request, "discovery-codespaces-identity-mismatch", codespace_name), "codespaces_capable": False}
    if payload.get("status") == "needs-decision" and payload.get("reason_codes") in (
        ["codespaces-discovery-repo-unavailable"],
        ["codespaces-discovery-import-failed"],
        ["codespaces-discovery-store-unavailable"],
    ):
        # No discovery capability on this surface: not capable, so the
        # workflow falls back through the existing GCE path.
        return {"discovery": payload, "codespaces_capable": False}
    return {"discovery": payload, "codespaces_capable": True}


def _ingress_from_file(path: Path) -> IssueCommentIngressResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        raise ValueError("transport evidence must be an object")
    keys = (
        "schema_version",
        "status",
        "reason",
        "repository",
        "issue_number",
        "comment_id",
        "actor",
        "handoff_id_or_none",
        "logical_trigger_id_or_none",
        "run_attempt",
        "dev_validation_branch_or_none",
        "dev_validation_sha_or_none",
        "dev_validation_id_or_none",
        "source_capsule_id_or_none",
        "first_run_candidate_sha_or_none",
        "notion_read_request_id_or_none",
        "diagnostic_id_or_none",
        "diagnostic_request_id_or_none",
        "ruleset_prestate_sha256_or_none",
    )
    return IssueCommentIngressResult(**{key: payload.get(key) for key in keys})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--route-output", type=Path, required=True)
    parser.add_argument("--result-output", type=Path, required=True)
    args = parser.parse_args(argv)

    ingress = _ingress_from_file(args.transport)
    route, request = select_codespaces_discovery(ingress)
    args.route_output.parent.mkdir(parents=True, exist_ok=True)
    args.route_output.write_text(
        json.dumps(route, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    if route.get("selected") is True and request is not None:
        result = run_discovery_over_codespaces(
            request, codespace_name=str(route.get("codespace_name"))
        )
    else:
        result = {"discovery": None, "codespaces_capable": False}
    args.result_output.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(json.dumps(route, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
