"""Fixed GitHub-to-GCE dev-validation transport for #1432/#1436/#1454/#1455."""
from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path
from typing import Mapping

from .dev_validation import (
    DevValidationRequest,
    REPOSITORY,
    VALIDATION_REGISTRY,
    build_dev_validation_request,
    validation_argv,
)
from .gce_control_path import VmState
from .gce_gcloud_adapter import GcloudIapAdapter, RESOURCE, _policy
from .github_issue_comment_ingress import IssueCommentIngressResult

HOST_PYTHON = "/usr/bin/python3"
DEV_VALIDATION_PYTHON = "/usr/local/libexec/agent-os-dev-validation-python"
_FRAME_START = "===AGENT-OS-DEV-VALIDATION-JSON-BEGIN==="
_FRAME_END = "===AGENT-OS-DEV-VALIDATION-JSON-END==="
MAX_RESULT_LOG_CHARS = 4096
_UNSAFE_DIAGNOSTIC_CHAR_RE = re.compile(r"[^\x09\x0a\x0d\x20-\x7e]")

_HOST_RUNNER_SOURCE = r'''import json,os,re,shutil,subprocess,sys,tempfile
REPOSITORY="Blummer92/agent-os"
REPO_URL="https://github.com/Blummer92/agent-os.git"
TEST_PYTHON="/usr/local/libexec/agent-os-dev-validation-python"
MATERIALS_ID="instructional-materials-current-curriculum-suite"
MATERIALS_IMPORT_ROOTS=("src","08_Tooling/instructional-materials-coach/src")
MATERIALS_IMPORT_PRELUDE="import os,sys;repo=os.getcwd();sys.path[:0]=[os.path.join(repo,path) for path in ('src','08_Tooling/instructional-materials-coach/src')]"
MATERIALS_IMPORT_PROBE=MATERIALS_IMPORT_PRELUDE+";import instructional_materials_coach,instructional_workflow_contracts"
MATERIALS_PYTEST_RUNNER=MATERIALS_IMPORT_PROBE+";import pytest;raise SystemExit(pytest.main(tuple(sys.argv[1:])))"
VALIDATION_ARGS={
 "remote-validation-suite":("-m","pytest","tests/agent_os_remote_validation"),
 MATERIALS_ID:(
  "-m","pytest",
  "08_Tooling/instructional-materials-coach/tests/test_generation_context.py",
  "08_Tooling/instructional-materials-coach/tests/test_content_spec.py",
  "08_Tooling/instructional-materials-coach/tests/test_cli.py",
  "tests/test_current_curriculum_state.py",
  "tests/test_current_curriculum_evidence.py",
 ),
}
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
 print(FRAME_START);print(json.dumps(payload,sort_keys=True,separators=(",",":")));print(FRAME_END)

def base(status,reason,repository,issue,branch,sha,validation_id,request_id):
 return {"schema_version":"1.0","status":status,"reason_codes":[reason],"repository":repository,"issue_number":issue,"branch":branch,"tested_sha":sha,"validation_id":validation_id,"request_id":request_id,"exit_code":None,"stdout_tail":"","stderr_tail":"","stdout_truncated":False,"stderr_truncated":False,"cleanup_complete":False,"workspace_side_effects_performed":False,"external_side_effects_performed":False,"production_state_mutated":False,"execution_authorized":False,"scheduler_invoked":False,"publication_invoked":False,"merge_authorized":False}

if len(sys.argv)!=7:
 emit(base("needs-decision","invalid-host-argv",REPOSITORY,0,"unavailable","unavailable","unavailable","unavailable"));raise SystemExit(0)
repository,issue_text,branch,sha,validation_id,request_id=sys.argv[1:]
try:issue=int(issue_text)
except ValueError:issue=0
valid_branch=BRANCH.fullmatch(branch) is not None and branch not in {"agent/","agent/main"} and ".." not in branch and "//" not in branch and not branch.endswith(("/","."))
if repository!=REPOSITORY or issue<1 or not valid_branch or SHA40.fullmatch(sha) is None or validation_id not in VALIDATION_ARGS or not request_id.startswith("dev-validation:"):
 emit(base("needs-decision","invalid-host-identity",repository,issue,branch,sha,validation_id,request_id));raise SystemExit(0)

test_args=VALIDATION_ARGS[validation_id]
result=base("needs-decision","host-runner-failed",repository,issue,branch,sha,validation_id,request_id)
root=tempfile.mkdtemp(prefix="agent-os-dev-validation-");repo=os.path.join(root,"repo");result["workspace_side_effects_performed"]=True
try:
 clone=run(("git","clone","--quiet","--no-checkout","--single-branch","--branch",branch,REPO_URL,repo))
 if clone.returncode!=0: result["reason_codes"]=["branch-clone-failed"]
 else:
  remote_head=run(("git","-C",repo,"rev-parse",f"refs/remotes/origin/{branch}"))
  if remote_head.returncode!=0 or remote_head.stdout.strip()!=sha: result["reason_codes"]=["branch-head-mismatch"]
  else:
   checkout=run(("git","-C",repo,"checkout","--quiet","--detach",sha));head=run(("git","-C",repo,"rev-parse","HEAD")) if checkout.returncode==0 else checkout
   if checkout.returncode!=0 or head.returncode!=0 or head.stdout.strip()!=sha: result["reason_codes"]=["checkout-head-mismatch"]
   elif not os.path.isfile(TEST_PYTHON) or not os.access(TEST_PYTHON,os.X_OK): result["reason_codes"]=["test-runtime-unavailable"]
   else:
    runtime=run((TEST_PYTHON,"-c","import pytest; assert pytest.__version__ == '8.3.5'"),timeout=10)
    if runtime.returncode!=0: result["reason_codes"]=["test-runtime-invalid"]
    else:
     home=os.path.join(root,"home");tmp=os.path.join(root,"tmp");os.mkdir(home);os.mkdir(tmp)
     env={"PATH":os.environ.get("PATH",""),"HOME":home,"TMPDIR":tmp,"PYTHONDONTWRITEBYTECODE":"1","PYTHONNOUSERSITE":"1"}
     import_ready=True
     if validation_id==MATERIALS_ID:
      probe=run((TEST_PYTHON,"-c",MATERIALS_IMPORT_PROBE),cwd=repo,env=env,timeout=10)
      if probe.returncode!=0:
       out,out_truncated=bounded(probe.stdout);err,err_truncated=bounded(probe.stderr)
       result.update({"status":"failure","reason_codes":["validation-import-preflight-failed"],"exit_code":probe.returncode,"stdout_tail":out,"stderr_tail":err,"stdout_truncated":out_truncated,"stderr_truncated":err_truncated});import_ready=False
     if import_ready:
      try:
       command=(TEST_PYTHON,"-c",MATERIALS_PYTEST_RUNNER,*test_args[2:]) if validation_id==MATERIALS_ID else (TEST_PYTHON,*test_args)
       completed=run(command,cwd=repo,env=env,timeout=TEST_TIMEOUT)
       out,out_truncated=bounded(completed.stdout);err,err_truncated=bounded(completed.stderr)
       result.update({"status":"success" if completed.returncode==0 else "failure","reason_codes":["validation-passed" if completed.returncode==0 else "validation-failed"],"exit_code":completed.returncode,"stdout_tail":out,"stderr_tail":err,"stdout_truncated":out_truncated,"stderr_truncated":err_truncated})
      except subprocess.TimeoutExpired as exc:
       out,out_truncated=bounded(exc.stdout if isinstance(exc.stdout,str) else "");err,err_truncated=bounded(exc.stderr if isinstance(exc.stderr,str) else "")
       result.update({"status":"timeout","reason_codes":["validation-timeout"],"stdout_tail":out,"stderr_tail":err,"stdout_truncated":out_truncated,"stderr_truncated":err_truncated})
finally:
 try: shutil.rmtree(root);result["cleanup_complete"]=True
 except OSError: result["cleanup_complete"]=False;result["status"]="needs-decision";result["reason_codes"]=["workspace-cleanup-failed"]
emit(result)
'''


def _host_command(request: object) -> str:
    if type(request) is not DevValidationRequest:
        raise TypeError("request must be exact DevValidationRequest")
    expected = VALIDATION_REGISTRY.get(request.validation_id)
    if expected is None or validation_argv(request) != expected:
        raise ValueError("dev-validation argv drift")
    return shlex.join((HOST_PYTHON, "-c", _HOST_RUNNER_SOURCE, request.repository, str(request.issue_number), request.branch, request.source_sha, request.validation_id, request.request_id))


def _extract_framed_payload(stdout: object) -> str | None:
    if type(stdout) is not str or stdout.count(_FRAME_START) != 1 or stdout.count(_FRAME_END) != 1:
        return None
    start=stdout.find(_FRAME_START);end=stdout.find(_FRAME_END)
    return stdout[start+len(_FRAME_START):end].strip() if start>=0 and end>start else None


def _failure(request: DevValidationRequest, reason: str) -> dict[str, object]:
    return {"schema_version":"1.0","status":"needs-decision","reason_codes":[reason],"repository":request.repository,"issue_number":request.issue_number,"branch":request.branch,"tested_sha":request.source_sha,"validation_id":request.validation_id,"request_id":request.request_id,"cleanup_complete":False,"workspace_side_effects_performed":False,"external_side_effects_performed":False,"production_state_mutated":False,"execution_authorized":False,"scheduler_invoked":False,"publication_invoked":False,"merge_authorized":False}


def _bounded_ssh_stderr(stderr: object) -> tuple[str, bool]:
    text=stderr if type(stderr) is str else "";sanitized=_UNSAFE_DIAGNOSTIC_CHAR_RE.sub("?",text)
    return sanitized[-MAX_RESULT_LOG_CHARS:],len(sanitized)>MAX_RESULT_LOG_CHARS


def _ssh_failure(request: DevValidationRequest, completed: object) -> dict[str, object]:
    evidence=_failure(request,"dev-validation-ssh-failed");tail,truncated=_bounded_ssh_stderr(getattr(completed,"stderr",""));returncode=getattr(completed,"returncode",None)
    evidence.update({"ssh_exit_code":returncode if type(returncode) is int else None,"ssh_stderr_tail":tail,"ssh_stderr_truncated":truncated});return evidence


def run_dev_validation_over_ssh(adapter: GcloudIapAdapter, request: DevValidationRequest) -> dict[str, object]:
    completed=adapter._ssh(RESOURCE,_host_command(request))
    if completed.returncode!=0:return _ssh_failure(request,completed)
    framed=_extract_framed_payload(completed.stdout)
    if framed is None:return _failure(request,"dev-validation-frame-invalid")
    try:payload=json.loads(framed)
    except json.JSONDecodeError:return _failure(request,"dev-validation-evidence-not-json")
    if type(payload) is not dict:return _failure(request,"dev-validation-evidence-malformed")
    fixed={"repository":request.repository,"issue_number":request.issue_number,"branch":request.branch,"tested_sha":request.source_sha,"validation_id":request.validation_id,"request_id":request.request_id,"external_side_effects_performed":False,"production_state_mutated":False,"execution_authorized":False,"scheduler_invoked":False,"publication_invoked":False,"merge_authorized":False}
    if any(payload.get(key)!=value for key,value in fixed.items()):return _failure(request,"dev-validation-evidence-identity-mismatch")
    if payload.get("status") not in {"success","failure","timeout","needs-decision"}:return _failure(request,"dev-validation-status-invalid")
    for key in ("stdout_tail","stderr_tail"):
        value=payload.get(key,"")
        if type(value) is not str or len(value)>MAX_RESULT_LOG_CHARS:return _failure(request,"dev-validation-log-bound-invalid")
    return payload


def execute_dev_validation_transport(ingress: IssueCommentIngressResult, *, claims: Mapping[str, object], adapter: GcloudIapAdapter) -> dict[str, object]:
    if ingress.status!="accepted" or ingress.reason!="accepted-dev-validation-envelope":raise ValueError("dev validation requires accepted canonical ingress evidence")
    if ingress.run_attempt!=1:raise ValueError("workflow reruns cannot perform dev validation")
    if ingress.handoff_id_or_none is not None:raise ValueError("dev validation must not carry a handoff identity")
    if ingress.issue_number is None or ingress.dev_validation_branch_or_none is None or ingress.dev_validation_sha_or_none is None or ingress.dev_validation_id_or_none is None:raise ValueError("dev validation ingress identity incomplete")
    request=build_dev_validation_request(repository=ingress.repository,issue_number=ingress.issue_number,branch=ingress.dev_validation_branch_or_none,source_sha=ingress.dev_validation_sha_or_none,validation_id=ingress.dev_validation_id_or_none)
    if not _policy().accepts(claims):return {"dev_validation":_failure(request,"claims-rejected")}
    if adapter.observe_state(RESOURCE) is not VmState.RUNNING:return {"dev_validation":_failure(request,"host-not-running")}
    return {"dev_validation":run_dev_validation_over_ssh(adapter,request)}


def _ingress_from_file(path: Path) -> IssueCommentIngressResult:
    payload=json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:raise ValueError("transport evidence must be an object")
    keys=("schema_version","status","reason","repository","issue_number","comment_id","actor","handoff_id_or_none","logical_trigger_id_or_none","run_attempt","dev_validation_branch_or_none","dev_validation_sha_or_none","dev_validation_id_or_none")
    return IssueCommentIngressResult(**{key:payload.get(key) for key in keys})


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ("repository","repository-owner","workflow-ref","ref","audience"):parser.add_argument("--"+flag,required=True)
    parser.add_argument("--transport",type=Path,required=True);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args(argv)
    claims={"repository":args.repository,"repository_owner":args.repository_owner,"workflow_ref":args.workflow_ref,"ref":args.ref,"aud":args.audience}
    evidence=execute_dev_validation_transport(_ingress_from_file(args.transport),claims=claims,adapter=GcloudIapAdapter());args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(evidence,sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8");print(json.dumps(evidence,sort_keys=True));return 0

if __name__=="__main__":raise SystemExit(main())