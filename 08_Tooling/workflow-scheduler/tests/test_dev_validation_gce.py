from __future__ import annotations

import json
from types import SimpleNamespace

import workflow_scheduler.governance.dev_validation_gce as live
from workflow_scheduler.governance.dev_validation import build_dev_validation_request
from workflow_scheduler.governance.gce_control_path import VmState
from workflow_scheduler.governance.github_issue_comment_ingress import IssueCommentIngressResult

SHA="a"*40;BRANCH="agent/1271-validation-profile-path-coverage"

def request(validation_id="remote-validation-suite"):return build_dev_validation_request(repository="Blummer92/agent-os",issue_number=1271,branch=BRANCH,source_sha=SHA,validation_id=validation_id)
def ingress():return IssueCommentIngressResult(schema_version="1.0",status="accepted",reason="accepted-dev-validation-envelope",repository="Blummer92/agent-os",issue_number=1271,comment_id=1,actor="Blummer92",handoff_id_or_none=None,logical_trigger_id_or_none="issue-comment-trigger:"+"b"*64,run_attempt=1,dev_validation_branch_or_none=BRANCH,dev_validation_sha_or_none=SHA,dev_validation_id_or_none="remote-validation-suite")
def claims(**overrides):
 values={"repository":"Blummer92/agent-os","repository_owner":"Blummer92","workflow_ref":live._policy().workflow_ref,"ref":"refs/heads/main","aud":live._policy().audience};values.update(overrides);return values

def payload(req,status="success",exit_code=0):return {"schema_version":"1.0","status":status,"reason_codes":["validation-passed" if status=="success" else "validation-failed"],"repository":req.repository,"issue_number":req.issue_number,"branch":req.branch,"tested_sha":req.source_sha,"validation_id":req.validation_id,"request_id":req.request_id,"exit_code":exit_code,"stdout_tail":"ok","stderr_tail":"","stdout_truncated":False,"stderr_truncated":False,"cleanup_complete":True,"workspace_side_effects_performed":True,"external_side_effects_performed":False,"production_state_mutated":False,"execution_authorized":False,"scheduler_invoked":False,"publication_invoked":False,"merge_authorized":False}

class Adapter:
 def __init__(self,state=VmState.RUNNING,result=None):self.state=state;self.result=result;self.calls=[]
 def observe_state(self,resource):self.calls.append("observe");return self.state
 def _ssh(self,resource,command):
  self.calls.append(("ssh",command));body=payload(request()) if self.result is None else self.result
  return SimpleNamespace(returncode=0,stdout=live._FRAME_START+"\n"+json.dumps(body)+"\n"+live._FRAME_END+"\n",stderr="")

def test_host_command_contains_only_fixed_runner_and_validated_identity():
 command=live._host_command(request());assert live.DEV_VALIDATION_PYTHON in command;assert "tests/agent_os_remote_validation" in command;assert BRANCH in command;assert SHA in command;assert "sudo" not in command;assert "pip install" not in command

def test_host_runner_uses_only_governed_test_runtime():
 source=live._HOST_RUNNER_SOURCE;assert 'TEST_PYTHON="/usr/local/libexec/agent-os-dev-validation-python"' in source;assert "test_args=VALIDATION_ARGS[validation_id]" in source;assert "(TEST_PYTHON,*test_args)" in source;assert "pip install" not in source;assert "sudo" not in source;assert "shutil.which" not in source;assert "test-runtime-unavailable" in source;assert "test-runtime-invalid" in source

def test_eia_host_command_accepts_only_canonical_fixed_profile():
 command=live._host_command(request(live.EIA_VALIDATION_ID));assert live.EIA_VALIDATION_ID in command;assert "eia_paddleocr_runtime_qualification.py" in command;assert "pip install" not in command;assert "sudo" not in command

def test_eia_host_runner_uses_system_python_and_fixed_script_only():
 source=live._HOST_RUNNER_SOURCE;assert 'EIA_ID="eia-paddleocr-runtime-qualification"' in source;assert 'EIA_SCRIPT="08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/eia_paddleocr_runtime_qualification.py"' in source;assert 'run((HOST_PYTHON,eia_script)' in source;assert "record_eia" in source;assert "runtime-dependency-missing" not in source;assert "pip install" not in source;assert "requests" not in source

def test_eia_profile_does_not_enter_legacy_registry():
 assert live.EIA_VALIDATION_ID not in live.VALIDATION_REGISTRY;assert live.validation_argv(request(live.EIA_VALIDATION_ID))==live.EIA_VALIDATION_ARGV

def test_sheets_smoke_host_command_accepts_only_canonical_fixed_profile():
 req=request(live.SHEETS_SMOKE_VALIDATION_ID);command=live._host_command(req);assert live.SHEETS_SMOKE_VALIDATION_ID in command;assert "visual_asset_sheets_smoke.py" in command;assert req.request_id in command;assert "pip install" not in command;assert "sudo" not in command

def test_sheets_smoke_profile_does_not_enter_legacy_registry():
 req=request(live.SHEETS_SMOKE_VALIDATION_ID);assert live.SHEETS_SMOKE_VALIDATION_ID not in live.VALIDATION_REGISTRY;assert live.validation_argv(req)==live.SHEETS_SMOKE_VALIDATION_ARGV

def test_sheets_smoke_host_runner_is_fail_closed_without_credential_injector():
 source=live._HOST_RUNNER_SOURCE;assert 'SHEETS_SMOKE_ID="visual-asset-sheets-smoke"' in source;assert 'SHEETS_SMOKE_SCRIPT="08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/visual_asset_sheets_smoke.py"' in source;assert "credential injector unavailable" in source;assert "values_get must remain unreachable" in source;assert "sheets-smoke-credential-injector-unavailable" in source;assert "GOOGLE_APPLICATION_CREDENTIALS" not in source;assert "access_token" not in source;assert "refresh_token" not in source;assert "client_secret" not in source

def test_sheets_smoke_identity_uses_only_fixed_repository_import_roots():
 source=live._HOST_RUNNER_SOURCE;assert 'SHEETS_SMOKE_IMPORT_ROOT="08_Tooling/workflow-scheduler/src"' in source;assert 'SHEETS_SMOKE_IMPORT_PRELUDE=' in source;assert "sys.path[:0]=[os.path.join(repo,path)" in source;assert 'SHEETS_SMOKE_PROBE=SHEETS_SMOKE_IMPORT_PRELUDE+' in source;assert 'env["PYTHONPATH"]' not in source;assert 'os.environ.get("PYTHONPATH"' not in source

def test_sheets_smoke_host_runner_uses_fixed_target_and_no_drive_or_notion_surface():
 source=live._HOST_RUNNER_SOURCE;assert "1S3GNwqu0ehPXUA1j4FEksH1uEMKlxyEwAZWfIADPfpo" in source;assert "'Approved Use Review'!A1:N455" in source;assert 'payload.get("drive_access_performed")' not in source;assert "drive.google" not in source;assert "api.notion" not in source

def test_successful_transport_remains_non_authorizing():
 result=live.execute_dev_validation_transport(ingress(),claims=claims(),adapter=Adapter());e=result["dev_validation"];assert e["status"]=="success";assert e["tested_sha"]==SHA;assert e["cleanup_complete"] is True;assert e["scheduler_invoked"] is False;assert e["execution_authorized"] is False;assert e["publication_invoked"] is False;assert e["merge_authorized"] is False

def test_wrong_claims_fail_before_ssh():
 adapter=Adapter();result=live.execute_dev_validation_transport(ingress(),claims=claims(repository="other/repo"),adapter=adapter);assert adapter.calls==[];assert result["dev_validation"]["reason_codes"]==["claims-rejected"]

def test_stopped_host_does_not_start():
 adapter=Adapter(state=VmState.STOPPED);result=live.execute_dev_validation_transport(ingress(),claims=claims(),adapter=adapter);assert adapter.calls==["observe"];assert result["dev_validation"]["reason_codes"]==["host-not-running"]

def test_ssh_failure_preserves_bounded_diagnostics():
 class Failed(Adapter):
  def _ssh(self,resource,command):return SimpleNamespace(returncode=255,stdout="",stderr="x"*(live.MAX_RESULT_LOG_CHARS+20)+" denied")
 e=live.execute_dev_validation_transport(ingress(),claims=claims(),adapter=Failed())["dev_validation"];assert e["reason_codes"]==["dev-validation-ssh-failed"];assert e["ssh_exit_code"]==255;assert len(e["ssh_stderr_tail"])==live.MAX_RESULT_LOG_CHARS;assert e["ssh_stderr_truncated"] is True

def test_identity_mismatch_fails_closed():
 bad=payload(request());bad["tested_sha"]="b"*40;result=live.execute_dev_validation_transport(ingress(),claims=claims(),adapter=Adapter(result=bad));assert result["dev_validation"]["reason_codes"]==["dev-validation-evidence-identity-mismatch"]

def test_unframed_output_is_not_trusted():
 class Bad(Adapter):
  def _ssh(self,resource,command):return SimpleNamespace(returncode=0,stdout='{"status":"success"}',stderr="")
 assert live.execute_dev_validation_transport(ingress(),claims=claims(),adapter=Bad())["dev_validation"]["reason_codes"]==["dev-validation-frame-invalid"]

def test_log_over_bound_is_rejected():
 bad=payload(request());bad["stdout_tail"]="x"*(live.MAX_RESULT_LOG_CHARS+1);assert live.execute_dev_validation_transport(ingress(),claims=claims(),adapter=Adapter(result=bad))["dev_validation"]["reason_codes"]==["dev-validation-log-bound-invalid"]
