"""Fixed GitHub-to-GCE dev-validation transport for #1432/#1436/#1454/#1455/#1495/#1515/#1768/#1942."""
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
EIA_VALIDATION_ID = "eia-paddleocr-runtime-qualification"
EIA_VALIDATION_ARGV = ("python", "-m", "workflow_scheduler.governance.eia_paddleocr_runtime_qualification")
SHEETS_SMOKE_VALIDATION_ID = "visual-asset-sheets-smoke"
SHEETS_SMOKE_VALIDATION_ARGV = ("python", "-m", "workflow_scheduler.governance.visual_asset_sheets_smoke")
# DEVVAL3 (#1495): the TypeScript/Vitest identity cannot run under the pinned
# CPython test runtime, so it binds a second fixed root-owned runtime published
# by the same separately authorized administrator installer pattern. It adds no
# caller-selectable interpreter, package, or argv surface.
DEV_VALIDATION_NODE = "/usr/local/libexec/agent-os-dev-validation-node"
DEV_VALIDATION_NODE_MODULES = "/opt/agent-os/dev-validation-node-runtime/node_modules"
DEV_VALIDATION_VITEST_VERSION = "4.1.10"
_FRAME_START = "===AGENT-OS-DEV-VALIDATION-JSON-BEGIN==="
_FRAME_END = "===AGENT-OS-DEV-VALIDATION-JSON-END==="
MAX_RESULT_LOG_CHARS = 4096
_UNSAFE_DIAGNOSTIC_CHAR_RE = re.compile(r"[^\x09\x0a\x0d\x20-\x7e]")

_HOST_RUNNER_SOURCE = r'''import json,os,re,shutil,subprocess,sys,tempfile
REPOSITORY="Blummer92/agent-os"
REPO_URL="https://github.com/Blummer92/agent-os.git"
HOST_PYTHON="/usr/bin/python3"
TEST_PYTHON="/usr/local/libexec/agent-os-dev-validation-python"
MATERIALS_ID="instructional-materials-current-curriculum-suite"
MATERIALS_IMPORT_ROOTS=("src","08_Tooling/instructional-materials-coach/src")
MATERIALS_IMPORT_PRELUDE="import os,sys;repo=os.getcwd();sys.path[:0]=[os.path.join(repo,path) for path in ('src','08_Tooling/instructional-materials-coach/src')]"
MATERIALS_IMPORT_PROBE=MATERIALS_IMPORT_PRELUDE+";import instructional_materials_coach,instructional_workflow_contracts"
MATERIALS_PYTEST_RUNNER=MATERIALS_IMPORT_PROBE+";import pytest;raise SystemExit(pytest.main(list(sys.argv[1:])))"
PPUX_ID="ppux-picture-perfect-ts-vitest"
PPUX_PACKAGE_DIR="08_Tooling/instructional-materials-coach/picture-perfect-coach"
EIA_ID="eia-paddleocr-runtime-qualification"
EIA_SCRIPT="08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/eia_paddleocr_runtime_qualification.py"
SHEETS_SMOKE_ID="visual-asset-sheets-smoke"
SHEETS_SMOKE_SCRIPT="08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/visual_asset_sheets_smoke.py"
SHEETS_SMOKE_IMPORT_ROOT="08_Tooling/workflow-scheduler/src"
SHEETS_SMOKE_PROBE="import json,sys;from workflow_scheduler.governance.visual_asset_sheets_smoke import build_request,execute_smoke;req=build_request(repository='Blummer92/agent-os',issue_number=734,source_sha=sys.argv[1],spreadsheet_id='1S3GNwqu0ehPXUA1j4FEksH1uEMKlxyEwAZWfIADPfpo',worksheet_name='Approved Use Review',a1_range=\"'Approved Use Review'!A1:N455\");inspect=lambda:(_ for _ in ()).throw(RuntimeError('credential injector unavailable'));read=lambda *_:(_ for _ in ()).throw(AssertionError('values_get must remain unreachable'));print(json.dumps(execute_smoke(req,inspect_effective_scopes=inspect,values_get=read),sort_keys=True,separators=(',',':')))"
NODE="/usr/local/libexec/agent-os-dev-validation-node"
NODE_MODULES="/opt/agent-os/dev-validation-node-runtime/node_modules"
VITEST_CLI=NODE_MODULES+"/vitest/vitest.mjs"
NODE_PROBE="const v=require(process.argv[1]+'/vitest/package.json').version;if(v!=='4.1.10'||!process.versions.node.startsWith('22.'))process.exit(1)"
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
 "semantic-ownership-advisory":("07_Agent_Tests/run-semantic-ownership-advisory-validation.py",),
 PPUX_ID:(
  "vitest","run",
  "src/overlayIntegrity.test.ts",
  "src/exactComposite.test.ts",
  "src/exactCompositeSuite.test.ts",
  "src/framePlan.test.ts",
  "src/executorContract.test.ts",
  "src/provenanceValidator.test.ts",
 ),
 EIA_ID:(EIA_SCRIPT,),
 SHEETS_SMOKE_ID:(SHEETS_SMOKE_SCRIPT,),
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

def fixed_env(root):
 home=os.path.join(root,"home");tmp=os.path.join(root,"tmp");os.mkdir(home);os.mkdir(tmp)
 return {"PATH":os.environ.get("PATH",""),"HOME":home,"TMPDIR":tmp,"PYTHONDONTWRITEBYTECODE":"1","PYTHONNOUSERSITE":"1"}

def record(result,completed):
 out,out_truncated=bounded(completed.stdout);err,err_truncated=bounded(completed.stderr)
 result.update({"status":"success" if completed.returncode==0 else "failure","reason_codes":["validation-passed" if completed.returncode==0 else "validation-failed"],"exit_code":completed.returncode,"stdout_tail":out,"stderr_tail":err,"stdout_truncated":out_truncated,"stderr_truncated":err_truncated})

def record_eia(result,completed):
 out,out_truncated=bounded(completed.stdout);err,err_truncated=bounded(completed.stderr)
 try:payload=json.loads(completed.stdout)
 except json.JSONDecodeError:
  result.update({"status":"needs-decision","reason_codes":["eia-qualification-output-invalid"],"exit_code":completed.returncode,"stdout_tail":out,"stderr_tail":err,"stdout_truncated":out_truncated,"stderr_truncated":err_truncated});return
 reasons=payload.get("reason_codes") if isinstance(payload,dict) else None
 flags=("network_used","installation_performed","model_download_performed","external_write_performed","execution_authorized","scheduler_invoked","production_authorized","classroom_data_authorized")
 valid_reasons=isinstance(reasons,list) and 0<len(reasons)<=16 and all(isinstance(value,str) and 0<len(value)<=160 for value in reasons)
 valid_flags=isinstance(payload,dict) and payload.get("synthetic_only") is True and all(payload.get(key) is False for key in flags)
 valid_status=isinstance(payload,dict) and payload.get("qualification_id")==EIA_ID and payload.get("status") in {"ready","blocked"}
 valid_exit=isinstance(payload,dict) and ((payload.get("status")=="ready" and completed.returncode==0) or (payload.get("status")=="blocked" and completed.returncode==2))
 if not (valid_reasons and valid_flags and valid_status and valid_exit):
  result.update({"status":"needs-decision","reason_codes":["eia-qualification-output-invalid"],"exit_code":completed.returncode,"stdout_tail":out,"stderr_tail":err,"stdout_truncated":out_truncated,"stderr_truncated":err_truncated});return
 result.update({"status":"success" if payload["status"]=="ready" else "needs-decision","reason_codes":reasons,"exit_code":completed.returncode,"stdout_tail":out,"stderr_tail":err,"stdout_truncated":out_truncated,"stderr_truncated":err_truncated})

def record_sheets_smoke(result,completed):
 out,out_truncated=bounded(completed.stdout);err,err_truncated=bounded(completed.stderr)
 try:payload=json.loads(completed.stdout)
 except json.JSONDecodeError:
  result.update({"status":"needs-decision","reason_codes":["sheets-smoke-output-invalid"],"exit_code":completed.returncode,"stdout_tail":out,"stderr_tail":err,"stdout_truncated":out_truncated,"stderr_truncated":err_truncated});return
 flags=("external_write_performed","sheet_write_performed","drive_access_performed","notion_access_performed","execution_authorized","production_authorized","credential_material_emitted")
 valid=isinstance(payload,dict) and completed.returncode==0 and payload.get("status")=="blocked" and payload.get("reason_codes")==["scope-unverifiable"] and payload.get("scope_verified") is False and payload.get("response_row_count")==0 and all(payload.get(key) is False for key in flags)
 if not valid:
  result.update({"status":"needs-decision","reason_codes":["sheets-smoke-output-invalid"],"exit_code":completed.returncode,"stdout_tail":out,"stderr_tail":err,"stdout_truncated":out_truncated,"stderr_truncated":err_truncated});return
 result.update({"status":"needs-decision","reason_codes":["sheets-smoke-credential-injector-unavailable"],"exit_code":0,"stdout_tail":"","stderr_tail":"","stdout_truncated":False,"stderr_truncated":False})

def record_timeout(result,exc):
 out,out_truncated=bounded(exc.stdout if isinstance(exc.stdout,str) else "");err,err_truncated=bounded(exc.stderr if isinstance(exc.stderr,str) else "")
 result.update({"status":"timeout","reason_codes":["validation-timeout"],"stdout_tail":out,"stderr_tail":err,"stdout_truncated":out_truncated,"stderr_truncated":err_truncated})

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
   elif validation_id==PPUX_ID:
    package=os.path.join(repo,PPUX_PACKAGE_DIR);link=os.path.join(package,"node_modules")
    if not os.path.isfile(NODE) or not os.access(NODE,os.X_OK) or not os.path.isfile(VITEST_CLI): result["reason_codes"]=["test-runtime-unavailable"]
    elif run((NODE,"-e",NODE_PROBE,NODE_MODULES),timeout=20).returncode!=0: result["reason_codes"]=["test-runtime-invalid"]
    elif not os.path.isdir(package) or os.path.lexists(link): result["reason_codes"]=["validation-workspace-unavailable"]
    else:
     env=fixed_env(root)
     # Node resolves dependencies by walking up from the test file, so the fixed
     # root-owned overlay is linked into the ephemeral checkout. rmtree removes
     # the link rather than descending it, so the overlay itself is untouched.
     os.symlink(NODE_MODULES,link)
     try:record(result,run((NODE,VITEST_CLI,*test_args[1:]),cwd=package,env=env,timeout=TEST_TIMEOUT))
     except subprocess.TimeoutExpired as exc:record_timeout(result,exc)
   elif validation_id==EIA_ID:
    eia_script=os.path.join(repo,EIA_SCRIPT)
    if not os.path.isfile(HOST_PYTHON) or not os.access(HOST_PYTHON,os.X_OK): result["reason_codes"]=["eia-host-python-unavailable"]
    elif not os.path.isfile(eia_script): result["reason_codes"]=["validation-workspace-unavailable"]
    else:
     env=fixed_env(root)
     try:record_eia(result,run((HOST_PYTHON,eia_script),cwd=repo,env=env,timeout=TEST_TIMEOUT))
     except subprocess.TimeoutExpired as exc:record_timeout(result,exc)
   elif validation_id==SHEETS_SMOKE_ID:
    sheets_script=os.path.join(repo,SHEETS_SMOKE_SCRIPT)
    if not os.path.isfile(HOST_PYTHON) or not os.access(HOST_PYTHON,os.X_OK): result["reason_codes"]=["sheets-smoke-host-python-unavailable"]
    elif not os.path.isfile(sheets_script): result["reason_codes"]=["validation-workspace-unavailable"]
    else:
     env=fixed_env(root);env["PYTHONPATH"]=os.path.join(repo,SHEETS_SMOKE_IMPORT_ROOT)
     try:record_sheets_smoke(result,run((HOST_PYTHON,"-c",SHEETS_SMOKE_PROBE,sha),cwd=repo,env=env,timeout=20))
     except subprocess.TimeoutExpired as exc:record_timeout(result,exc)
   elif not os.path.isfile(TEST_PYTHON) or not os.access(TEST_PYTHON,os.X_OK): result["reason_codes"]=["test-runtime-unavailable"]
   else:
    runtime=run((TEST_PYTHON,"-c","import pytest; assert pytest.__version__ == '8.3.5'"),timeout=10)
    if runtime.returncode!=0: result["reason_codes"]=["test-runtime-invalid"]
    else:
     env=fixed_env(root)
     import_ready=True
     if validation_id==MATERIALS_ID:
      probe=run((TEST_PYTHON,"-c",MATERIALS_IMPORT_PROBE),cwd=repo,env=env,timeout=10)
      if probe.returncode!=0:
       out,out_truncated=bounded(probe.stdout);err,err_truncated=bounded(probe.stderr)
       result.update({"status":"failure","reason_codes":["validation-import-preflight-failed"],"exit_code":probe.returncode,"stdout_tail":out,"stderr_tail":err,"stdout_truncated":out_truncated,"stderr_truncated":err_truncated});import_ready=False
     if import_ready:
      try:
       command=(TEST_PYTHON,"-c",MATERIALS_PYTEST_RUNNER,*test_args[2:]) if validation_id==MATERIALS_ID else (TEST_PYTHON,*test_args)
       record(result,run(command,cwd=repo,env=env,timeout=TEST_TIMEOUT))
      except subprocess.TimeoutExpired as exc:record_timeout(result,exc)
finally:
 try: shutil.rmtree(root);result["cleanup_complete"]=True
 except OSError: result["cleanup_complete"]=False;result["status"]="needs-decision";result["reason_codes"]=["workspace-cleanup-failed"]
emit(result)
'''


def _host_command(request: object) -> str:
    if type(request) is not DevValidationRequest:
        raise TypeError("request must be exact DevValidationRequest")
    expected = VALIDATION_REGISTRY.get(request.validation_id)
    if request.validation_id == EIA_VALIDATION_ID:
        expected = EIA_VALIDATION_ARGV
    elif request.validation_id == SHEETS_SMOKE_VALIDATION_ID:
        expected = SHEETS_SMOKE_VALIDATION_ARGV
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