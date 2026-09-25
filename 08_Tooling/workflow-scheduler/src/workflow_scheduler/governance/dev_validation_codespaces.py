"""Read-only GitHub-to-Codespaces developer-validation transport for #2931.

This provider adapter consumes only the existing accepted developer-validation
request contract. It never starts, stops, edits, creates, deletes, or exports a
Codespace. If the single approved Codespace is not already Available, the caller
falls back through the existing governed-runner path.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable

from .dev_validation import (
    DevValidationRequest,
    REPOSITORY,
    VALIDATION_ID,
    build_dev_validation_request,
)
from .github_issue_comment_ingress import IssueCommentIngressResult

APPROVED_CODESPACE_NAME = "literate-system-j4j4pr9g4q7h45q"
APPROVED_CODESPACE_PROFILE_ID = "agent-os-codespaces-v1"
APPROVED_CODESPACE_SURFACE_ID = f"codespace:{APPROVED_CODESPACE_NAME}"
APPROVED_OWNER = "Blummer92"
SUPPORTED_VALIDATION_IDS = frozenset({VALIDATION_ID})
_FRAME_START = "===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-BEGIN==="
_FRAME_END = "===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-END==="
MAX_RESULT_LOG_CHARS = 4096
_RUN_TIMEOUT_SECONDS = 240
_UNSAFE_DIAGNOSTIC_CHAR_RE = re.compile(r"[^\x09\x0a\x0d\x20-\x7e]")

_REMOTE_RUNNER_SOURCE = r'''import hashlib,json,os,re,shutil,subprocess,sys,tempfile
REPOSITORY="Blummer92/agent-os"
VALIDATION_ID="remote-validation-suite"
CANONICAL_PROFILE_ID="remote-validation"
PROFILE_ID="agent-os-codespaces-v1"
FRAME_START="===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-BEGIN==="
FRAME_END="===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-END==="
SHA40=re.compile(r"^[0-9a-f]{40}$",re.ASCII)
BRANCH=re.compile(r"^agent/[A-Za-z0-9._/-]{1,180}$",re.ASCII)
MAX_LOG=4096

def bounded(value):
 value=value if isinstance(value,str) else ""
 return value[-MAX_LOG:],len(value)>MAX_LOG

def run(argv,*,cwd=None,env=None,timeout=120):
 return subprocess.run(tuple(argv),cwd=cwd,env=env,check=False,capture_output=True,text=True,timeout=timeout)

def base(status,reason,repository,issue,branch,sha,validation_id,request_id):
 return {"schema_version":"1.0","status":status,"reason_codes":[reason],"repository":repository,"issue_number":issue,"branch":branch,"tested_sha":sha,"validation_id":validation_id,"request_id":request_id,"exit_code":None,"stdout_tail":"","stderr_tail":"","stdout_truncated":False,"stderr_truncated":False,"cleanup_complete":False,"workspace_side_effects_performed":False,"external_side_effects_performed":False,"production_state_mutated":False,"execution_authorized":False,"scheduler_invoked":False,"publication_invoked":False,"merge_authorized":False,"codespaces_profile_id":PROFILE_ID,"execution_surface_id":None,"environment_health_evidence_id":None}

def emit(payload):
 print(FRAME_START);print(json.dumps(payload,sort_keys=True,separators=(",",":")));print(FRAME_END)

if len(sys.argv)!=8:
 emit(base("needs-decision","invalid-codespaces-host-argv",REPOSITORY,0,"unavailable","unavailable","unavailable","unavailable"));raise SystemExit(0)
repository,issue_text,branch,sha,validation_id,request_id,codespace_name=sys.argv[1:]
try:issue=int(issue_text)
except ValueError:issue=0
valid_branch=BRANCH.fullmatch(branch) is not None and branch not in {"agent/","agent/main"} and ".." not in branch and "//" not in branch and not branch.endswith(("/","."))
material=json.dumps([repository,issue,branch,sha,CANONICAL_PROFILE_ID],separators=(",",":"),ensure_ascii=True).encode("ascii") if issue>0 else b""
expected_request_id="dev-validation:"+hashlib.sha256(b"agent-os-dev-validation:v2\0"+material).hexdigest() if material else ""
result=base("needs-decision","codespaces-host-runner-failed",repository,issue,branch,sha,validation_id,request_id)
if repository!=REPOSITORY or issue<1 or not valid_branch or SHA40.fullmatch(sha) is None or validation_id!=VALIDATION_ID or request_id!=expected_request_id:
 result["reason_codes"]=["invalid-codespaces-host-identity"];emit(result);raise SystemExit(0)
if os.environ.get("CODESPACE_NAME")!=codespace_name:
 result["reason_codes"]=["codespaces-surface-identity-mismatch"];emit(result);raise SystemExit(0)
primary="/workspaces/agent-os"
if not os.path.isdir(primary):
 result["reason_codes"]=["codespaces-workspace-unavailable"];emit(result);raise SystemExit(0)
health=run(("python3","scripts/agent-os-environment-health.py","--execution-surface-id",f"codespace:{codespace_name}"),cwd=primary,timeout=20)
try:health_payload=json.loads(health.stdout)
except json.JSONDecodeError:health_payload={}
authority=health_payload.get("authority") if isinstance(health_payload,dict) else None
safe_authority=isinstance(authority,dict) and authority and all(value is False for value in authority.values())
if health.returncode!=0 or health_payload.get("status")!="pass" or health_payload.get("profile_id")!=PROFILE_ID or health_payload.get("execution_surface_id")!=f"codespace:{codespace_name}" or not safe_authority:
 result["reason_codes"]=["codespaces-environment-health-invalid"];emit(result);raise SystemExit(0)
result["execution_surface_id"]=health_payload["execution_surface_id"]
result["environment_health_evidence_id"]=health_payload.get("environment_health_evidence_id")
remote=run(("git","ls-remote","--heads","origin",f"refs/heads/{branch}"),cwd=primary,timeout=30)
parts=remote.stdout.strip().split()
if remote.returncode!=0 or len(parts)!=2 or parts[0]!=sha:
 result["reason_codes"]=["branch-head-mismatch"];emit(result);raise SystemExit(0)
exists=run(("git","cat-file","-e",f"{sha}^{{commit}}"),cwd=primary,timeout=10)
if exists.returncode!=0:
 fetch=run(("git","fetch","--quiet","origin",sha),cwd=primary,timeout=60)
 if fetch.returncode!=0:
  result["reason_codes"]=["source-fetch-failed"];emit(result);raise SystemExit(0)
runtime=run(("python3","-c","import pytest; assert pytest.__version__ == '8.3.5'"),cwd=primary,timeout=10)
if runtime.returncode!=0:
 result["reason_codes"]=["test-runtime-invalid"];emit(result);raise SystemExit(0)
root=tempfile.mkdtemp(prefix="agent-os-codespaces-dev-validation-")
worktree=os.path.join(root,"repo")
result["workspace_side_effects_performed"]=True
try:
 add=run(("git","worktree","add","--detach",worktree,sha),cwd=primary,timeout=60)
 if add.returncode!=0:
  result["reason_codes"]=["worktree-create-failed"]
 else:
  head=run(("git","rev-parse","HEAD"),cwd=worktree,timeout=10)
  if head.returncode!=0 or head.stdout.strip()!=sha:
   result["reason_codes"]=["checkout-head-mismatch"]
  else:
   try:
    completed=run(("python3","-m","pytest","tests/agent_os_remote_validation"),cwd=worktree,env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1","PYTHONNOUSERSITE":"1"},timeout=120)
    out,out_truncated=bounded(completed.stdout);err,err_truncated=bounded(completed.stderr)
    result.update({"status":"success" if completed.returncode==0 else "failure","reason_codes":["validation-passed" if completed.returncode==0 else "validation-failed"],"exit_code":completed.returncode,"stdout_tail":out,"stderr_tail":err,"stdout_truncated":out_truncated,"stderr_truncated":err_truncated})
   except subprocess.TimeoutExpired as exc:
    out,out_truncated=bounded(exc.stdout if isinstance(exc.stdout,str) else "");err,err_truncated=bounded(exc.stderr if isinstance(exc.stderr,str) else "")
    result.update({"status":"timeout","reason_codes":["validation-timeout"],"exit_code":None,"stdout_tail":out,"stderr_tail":err,"stdout_truncated":out_truncated,"stderr_truncated":err_truncated})
finally:
 remove=run(("git","worktree","remove","--force",worktree),cwd=primary,timeout=30) if os.path.exists(worktree) else None
 try:shutil.rmtree(root)
 except OSError:pass
 result["cleanup_complete"]=not os.path.exists(root) and (remove is None or remove.returncode==0)
 if not result["cleanup_complete"]:
  result["status"]="needs-decision";result["reason_codes"]=["workspace-cleanup-failed"]
emit(result)
'''

Run = Callable[..., subprocess.CompletedProcess[str]]


def _run(
    argv: tuple[str, ...], *, timeout: int = _RUN_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, check=False, capture_output=True, text=True, timeout=timeout
    )


def _bounded_text(value: object) -> tuple[str, bool]:
    text = value if type(value) is str else ""
    sanitized = _UNSAFE_DIAGNOSTIC_CHAR_RE.sub("?", text)
    return sanitized[-MAX_RESULT_LOG_CHARS:], len(sanitized) > MAX_RESULT_LOG_CHARS


def _failure(request: DevValidationRequest, reason: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": "needs-decision",
        "reason_codes": [reason],
        "repository": request.repository,
        "issue_number": request.issue_number,
        "branch": request.branch,
        "tested_sha": request.source_sha,
        "validation_id": request.validation_id,
        "request_id": request.request_id,
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "cleanup_complete": False,
        "workspace_side_effects_performed": False,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
        "codespaces_profile_id": APPROVED_CODESPACE_PROFILE_ID,
        "execution_surface_id": APPROVED_CODESPACE_SURFACE_ID,
        "environment_health_evidence_id": None,
    }


def _route(
    selected: bool, reason: str, *, state: str | None = None
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "selected": selected,
        "reason_codes": [reason],
        "codespace_name": APPROVED_CODESPACE_NAME,
        "codespaces_profile_id": APPROVED_CODESPACE_PROFILE_ID,
        "execution_surface_id": APPROVED_CODESPACE_SURFACE_ID,
        "repository": REPOSITORY,
        "state": state,
        "credential_permission": "codespaces:read",
        "lifecycle_mutation_authorized": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "external_writes_authorized": False,
        "side_effects_performed": False,
    }


def _request_from_ingress(
    ingress: IssueCommentIngressResult,
) -> DevValidationRequest:
    if (
        ingress.status != "accepted"
        or ingress.reason != "accepted-dev-validation-envelope"
    ):
        raise ValueError(
            "dev validation requires accepted canonical ingress evidence"
        )
    if ingress.run_attempt != 1:
        raise ValueError("workflow reruns cannot perform dev validation")
    if ingress.handoff_id_or_none is not None:
        raise ValueError("dev validation must not carry a handoff identity")
    if (
        ingress.issue_number is None
        or ingress.dev_validation_branch_or_none is None
        or ingress.dev_validation_sha_or_none is None
        or ingress.dev_validation_id_or_none is None
    ):
        raise ValueError("dev validation ingress identity incomplete")
    return build_dev_validation_request(
        repository=ingress.repository,
        issue_number=ingress.issue_number,
        branch=ingress.dev_validation_branch_or_none,
        source_sha=ingress.dev_validation_sha_or_none,
        validation_id=ingress.dev_validation_id_or_none,
    )


def _inspect_approved_codespace(
    run: Run = _run,
) -> tuple[dict[str, object] | None, str]:
    if not os.environ.get("GH_TOKEN"):
        return None, "codespaces-credential-unavailable"
    completed = run(
        (
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            f"/user/codespaces/{APPROVED_CODESPACE_NAME}",
        ),
        timeout=30,
    )
    if completed.returncode != 0:
        return None, "codespaces-read-unavailable"
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None, "codespaces-read-evidence-invalid"
    if type(payload) is not dict:
        return None, "codespaces-read-evidence-invalid"
    return payload, "codespaces-read-proven"


def select_codespaces_dev_validation(
    ingress: IssueCommentIngressResult,
    *,
    run: Run = _run,
) -> tuple[dict[str, object], DevValidationRequest | None]:
    if (
        ingress.status != "accepted"
        or ingress.reason != "accepted-dev-validation-envelope"
    ):
        return _route(False, "not-dev-validation"), None
    request = _request_from_ingress(ingress)
    if request.validation_id not in SUPPORTED_VALIDATION_IDS:
        return _route(False, "codespaces-profile-not-qualified"), request
    payload, reason = _inspect_approved_codespace(run)
    if payload is None:
        return _route(False, reason), request
    repository = payload.get("repository")
    owner = payload.get("owner")
    repo_name = (
        repository.get("full_name") if type(repository) is dict else None
    )
    owner_login = owner.get("login") if type(owner) is dict else None
    name = payload.get("name")
    state = payload.get("state")
    if (
        name != APPROVED_CODESPACE_NAME
        or repo_name != REPOSITORY
        or owner_login != APPROVED_OWNER
    ):
        return (
            _route(
                False,
                "codespaces-identity-mismatch",
                state=state if type(state) is str else None,
            ),
            request,
        )
    if state != "Available":
        return (
            _route(
                False,
                "codespaces-not-available",
                state=state if type(state) is str else None,
            ),
            request,
        )
    return _route(True, "codespaces-capable", state="Available"), request


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


def run_dev_validation_over_codespaces(
    request: DevValidationRequest,
    *,
    run: Run = _run,
) -> dict[str, object]:
    completed = run(
        (
            "gh",
            "codespace",
            "ssh",
            "-c",
            APPROVED_CODESPACE_NAME,
            "--",
            "python3",
            "-c",
            _REMOTE_RUNNER_SOURCE,
            request.repository,
            str(request.issue_number),
            request.branch,
            request.source_sha,
            request.validation_id,
            request.request_id,
            APPROVED_CODESPACE_NAME,
        ),
        timeout=_RUN_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        evidence = _failure(
            request, "dev-validation-codespaces-ssh-failed"
        )
        tail, truncated = _bounded_text(completed.stderr)
        evidence.update(
            {
                "ssh_exit_code": completed.returncode,
                "ssh_stderr_tail": tail,
                "ssh_stderr_truncated": truncated,
            }
        )
        return evidence
    framed = _extract_framed_payload(completed.stdout)
    if framed is None:
        return _failure(
            request, "dev-validation-codespaces-frame-invalid"
        )
    try:
        payload = json.loads(framed)
    except json.JSONDecodeError:
        return _failure(
            request, "dev-validation-codespaces-evidence-not-json"
        )
    if type(payload) is not dict:
        return _failure(
            request, "dev-validation-codespaces-evidence-malformed"
        )
    fixed = {
        "repository": request.repository,
        "issue_number": request.issue_number,
        "branch": request.branch,
        "tested_sha": request.source_sha,
        "validation_id": request.validation_id,
        "request_id": request.request_id,
        "codespaces_profile_id": APPROVED_CODESPACE_PROFILE_ID,
        "execution_surface_id": APPROVED_CODESPACE_SURFACE_ID,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }
    if any(payload.get(key) != value for key, value in fixed.items()):
        return _failure(
            request, "dev-validation-codespaces-evidence-identity-mismatch"
        )
    if payload.get("status") not in {
        "success",
        "failure",
        "timeout",
        "needs-decision",
    }:
        return _failure(
            request, "dev-validation-codespaces-status-invalid"
        )
    environment_id = payload.get("environment_health_evidence_id")
    if (
        type(environment_id) is not str
        or not environment_id.startswith("sha256:")
    ):
        return _failure(
            request, "codespaces-environment-health-evidence-invalid"
        )
    for key in ("stdout_tail", "stderr_tail"):
        value = payload.get(key, "")
        if (
            type(value) is not str
            or len(value) > MAX_RESULT_LOG_CHARS
        ):
            return _failure(
                request, "dev-validation-codespaces-log-bound-invalid"
            )
    return payload


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
    )
    return IssueCommentIngressResult(
        **{key: payload.get(key) for key in keys}
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--route-output", type=Path, required=True)
    parser.add_argument("--result-output", type=Path, required=True)
    args = parser.parse_args(argv)
    ingress = _ingress_from_file(args.transport)
    route, request = select_codespaces_dev_validation(ingress)
    args.route_output.parent.mkdir(parents=True, exist_ok=True)
    args.route_output.write_text(
        json.dumps(route, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    if route["selected"] is True:
        assert request is not None
        evidence = {
            "dev_validation": run_dev_validation_over_codespaces(request)
        }
        args.result_output.parent.mkdir(parents=True, exist_ok=True)
        args.result_output.write_text(
            json.dumps(
                evidence, sort_keys=True, separators=(",", ":")
            )
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps(route, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
