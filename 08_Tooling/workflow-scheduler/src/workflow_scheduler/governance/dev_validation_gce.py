"""Fixed GitHub-to-GCE dev-validation transport for #1432.

This module reuses the existing GcloudIapAdapter._ssh() transport but exposes no
caller-supplied command or argv surface.  The only host operation is a fixed
repository-owned Python runner that clones one exact non-protected branch,
proves the requested SHA is the current remote branch head, executes the one
registered validation command, returns bounded JSON evidence, and removes its
temporary workspace.
"""
from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Mapping

from .dev_validation import (
    DevValidationRequest,
    REPOSITORY,
    VALIDATION_ARGV,
    build_dev_validation_request,
    validation_argv,
)
from .gce_control_path import VmState
from .gce_gcloud_adapter import (
    GcloudIapAdapter,
    RESOURCE,
    _policy,
)
from .github_issue_comment_ingress import IssueCommentIngressResult

HOST_PYTHON = "/usr/bin/python3"
_FRAME_START = "===AGENT-OS-DEV-VALIDATION-JSON-BEGIN==="
_FRAME_END = "===AGENT-OS-DEV-VALIDATION-JSON-END==="
MAX_RESULT_LOG_CHARS = 4096

# The host program is fixed in canonical workflow source. Candidate-branch files
# never choose this program, its argv, repository, timeout, or output contract.
_HOST_RUNNER_SOURCE = r'''import json,os,re,shutil,subprocess,sys,tempfile
REPOSITORY="Blummer92/agent-os"
REPO_URL="https://github.com/Blummer92/agent-os.git"
VALIDATION_ID="remote-validation-suite"
TEST_ARGS=("-m","pytest","tests/agent_os_remote_validation")
SHA40=re.compile(r"^[0-9a-f]{40}$",re.ASCII)
BRANCH=re.compile(r"^agent/[A-Za-z0-9._/-]{1,180}$",re.ASCII)
MAX_LOG=4096
TEST_TIMEOUT=120
GIT_TIMEOUT=120
FRAME_START="===AGENT-OS-DEV-VALIDATION-JSON-BEGIN==="
FRAME_END="===AGENT-OS-DEV-VALIDATION-JSON-END==="

def bounded(value):
 value=value if isinstance(value,str) else ""
 return value[-MAX_LOG:],len(value)>MAX_LOG

def run(argv,*,cwd=None,env=None,timeout=GIT_TIMEOUT):
 return subprocess.run(tuple(argv),cwd=cwd,env=env,check=False,capture_output=True,text=True,timeout=timeout)

def emit(payload):
 print(FRAME_START)
 print(json.dumps(payload,sort_keys=True,separators=(",",":")))
 print(FRAME_END)

def base(status,reason,repository,issue,branch,sha,validation_id,request_id):
 return {"schema_version":"1.0","status":status,"reason_codes":[reason],"repository":repository,"issue_number":issue,"branch":branch,"tested_sha":sha,"validation_id":validation_id,"request_id":request_id,"exit_code":None,"stdout_tail":"","stderr_tail":"","stdout_truncated":False,"stderr_truncated":False,"cleanup_complete":False,"workspace_side_effects_performed":False,"external_side_effects_performed":False,"production_state_mutated":False,"execution_authorized":False,"scheduler_invoked":False,"publication_invoked":False,"merge_authorized":False}

if len(sys.argv)!=7:
 emit(base("needs-decision","invalid-host-argv",REPOSITORY,0,"unavailable","unavailable",VALIDATION_ID,"unavailable"));raise SystemExit(0)
repository,issue_text,branch,sha,validation_id,request_id=sys.argv[1:]
try:issue=int(issue_text)
except ValueError:issue=0
valid_branch=BRANCH.fullmatch(branch) is not None and branch not in {"agent/","agent/main"} and ".." not in branch and "//" not in branch and not branch.endswith(("/","."))
if repository!=REPOSITORY or issue<1 or not valid_branch or SHA40.fullmatch(sha) is None or validation_id!=VALIDATION_ID or not request_id.startswith("dev-validation:"):
 emit(base("needs-decision","invalid-host-identity",repository,issue,branch,sha,validation_id,request_id));raise SystemExit(0)

result=base("needs-decision","host-runner-failed",repository,issue,branch,sha,validation_id,request_id)
root=tempfile.mkdtemp(prefix="agent-os-dev-validation-")
repo=os.path.join(root,"repo")
result["workspace_side_effects_performed"]=True
try:
 clone=run(("git","clone","--quiet","--no-checkout","--single-branch","--branch",branch,REPO_URL,repo))
 if clone.returncode!=0:
  result["reason_codes"]=["branch-clone-failed"]
 else:
  remote_head=run(("git","-C",repo,"rev-parse",f"refs/remotes/origin/{branch}"))
  if remote_head.returncode!=0 or remote_head.stdout.strip()!=sha:
   result["reason_codes"]=["branch-head-mismatch"]
  else:
   checkout=run(("git","-C",repo,"checkout","--quiet","--detach",sha))
   head=run(("git","-C",repo,"rev-parse","HEAD")) if checkout.returncode==0 else checkout
   if checkout.returncode!=0 or head.returncode!=0 or head.stdout.strip()!=sha:
    result["reason_codes"]=["checkout-head-mismatch"]
   else:
    python=shutil.which("python")
    if python is None:
     result["reason_codes"]=["runtime-python-unavailable"]
    else:
     home=os.path.join(root,"home");tmp=os.path.join(root,"tmp")
     os.mkdir(home);os.mkdir(tmp)
     env={"PATH":os.environ.get("PATH",""),"HOME":home,"TMPDIR":tmp,"PYTHONDONTWRITEBYTECODE":"1","PYTHONNOUSERSITE":"1"}
     try:
      completed=run((python,*TEST_ARGS),cwd=repo,env=env,timeout=TEST_TIMEOUT)
      out,out_truncated=bounded(completed.stdout);err,err_truncated=bounded(completed.stderr)
      result.update({"status":"success" if completed.returncode==0 else "failure","reason_codes":["validation-passed" if completed.returncode==0 else "validation-failed"],"exit_code":completed.returncode,"stdout_tail":out,"stderr_tail":err,"stdout_truncated":out_truncated,"stderr_truncated":err_truncated})
     except subprocess.TimeoutExpired as exc:
      out,out_truncated=bounded(exc.stdout if isinstance(exc.stdout,str) else "");err,err_truncated=bounded(exc.stderr if isinstance(exc.stderr,str) else "")
      result.update({"status":"timeout","reason_codes":["validation-timeout"],"stdout_tail":out,"stderr_tail":err,"stdout_truncated":out_truncated,"stderr_truncated":err_truncated})
finally:
 try:
  shutil.rmtree(root)
  result["cleanup_complete"]=True
 except OSError:
  result["cleanup_complete"]=False
  result["status"]="needs-decision"
  result["reason_codes"]=["workspace-cleanup-failed"]
emit(result)
'''


def _host_command(request: object) -> str:
    if type(request) is not DevValidationRequest:
        raise TypeError("request must be exact DevValidationRequest")
    argv = validation_argv(request)
    if argv != VALIDATION_ARGV:
        raise ValueError("dev-validation argv drift")
    args = (
        HOST_PYTHON,
        "-c",
        _HOST_RUNNER_SOURCE,
        request.repository,
        str(request.issue_number),
        request.branch,
        request.source_sha,
        request.validation_id,
        request.request_id,
    )
    return shlex.join(args)


def _extract_framed_payload(stdout: object) -> str | None:
    if type(stdout) is not str:
        return None
    if stdout.count(_FRAME_START) != 1 or stdout.count(_FRAME_END) != 1:
        return None
    start = stdout.find(_FRAME_START)
    end = stdout.find(_FRAME_END)
    if start < 0 or end <= start:
        return None
    return stdout[start + len(_FRAME_START):end].strip()


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
        "cleanup_complete": False,
        "workspace_side_effects_performed": False,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }


def run_dev_validation_over_ssh(
    adapter: GcloudIapAdapter,
    request: DevValidationRequest,
) -> dict[str, object]:
    command = _host_command(request)
    completed = adapter._ssh(RESOURCE, command)
    if completed.returncode != 0:
        return _failure(request, "dev-validation-ssh-failed")
    framed = _extract_framed_payload(completed.stdout)
    if framed is None:
        return _failure(request, "dev-validation-frame-invalid")
    try:
        payload = json.loads(framed)
    except json.JSONDecodeError:
        return _failure(request, "dev-validation-evidence-not-json")
    if type(payload) is not dict:
        return _failure(request, "dev-validation-evidence-malformed")
    fixed = {
        "repository": request.repository,
        "issue_number": request.issue_number,
        "branch": request.branch,
        "tested_sha": request.source_sha,
        "validation_id": request.validation_id,
        "request_id": request.request_id,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }
    if any(payload.get(key) != value for key, value in fixed.items()):
        return _failure(request, "dev-validation-evidence-identity-mismatch")
    if payload.get("status") not in {"success", "failure", "timeout", "needs-decision"}:
        return _failure(request, "dev-validation-status-invalid")
    for key in ("stdout_tail", "stderr_tail"):
        value = payload.get(key, "")
        if type(value) is not str or len(value) > MAX_RESULT_LOG_CHARS:
            return _failure(request, "dev-validation-log-bound-invalid")
    return payload


def execute_dev_validation_transport(
    ingress: IssueCommentIngressResult,
    *,
    claims: Mapping[str, object],
    adapter: GcloudIapAdapter,
) -> dict[str, object]:
    if ingress.status != "accepted" or ingress.reason != "accepted-dev-validation-envelope":
        raise ValueError("dev validation requires accepted canonical ingress evidence")
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
    request = build_dev_validation_request(
        repository=ingress.repository,
        issue_number=ingress.issue_number,
        branch=ingress.dev_validation_branch_or_none,
        source_sha=ingress.dev_validation_sha_or_none,
        validation_id=ingress.dev_validation_id_or_none,
    )
    if not _policy().accepts(claims):
        return {"dev_validation": _failure(request, "claims-rejected")}
    if adapter.observe_state(RESOURCE) is not VmState.RUNNING:
        return {"dev_validation": _failure(request, "host-not-running")}
    return {"dev_validation": run_dev_validation_over_ssh(adapter, request)}


def _ingress_from_file(path: Path) -> IssueCommentIngressResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        raise ValueError("transport evidence must be an object")
    keys = (
        "schema_version", "status", "reason", "repository", "issue_number",
        "comment_id", "actor", "handoff_id_or_none", "logical_trigger_id_or_none",
        "run_attempt", "dev_validation_branch_or_none", "dev_validation_sha_or_none",
        "dev_validation_id_or_none",
    )
    return IssueCommentIngressResult(**{key: payload.get(key) for key in keys})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repository-owner", required=True)
    parser.add_argument("--workflow-ref", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--audience", required=True)
    args = parser.parse_args(argv)
    claims = {
        "repository": args.repository,
        "repository_owner": args.repository_owner,
        "workflow_ref": args.workflow_ref,
        "ref": args.ref,
        "aud": args.audience,
    }
    evidence = execute_dev_validation_transport(
        _ingress_from_file(args.transport),
        claims=claims,
        adapter=GcloudIapAdapter(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
