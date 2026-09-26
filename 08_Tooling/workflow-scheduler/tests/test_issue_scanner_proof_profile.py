from __future__ import annotations

import json
from types import SimpleNamespace

import workflow_scheduler.governance.dev_validation_gce as live
from workflow_scheduler.governance.dev_validation import build_dev_validation_request, validation_argv
from workflow_scheduler.governance.dev_validation_profiles import RunnerKind, get_profile, profile_argv
from workflow_scheduler.governance.github_issue_comment_ingress import admit_issue_comment_event

SHA="a"*40
BRANCH="agent/1762-scanner-proof-profile"
REPOSITORY="Blummer92/agent-os"
ACTOR="Blummer92"

def request():
 return build_dev_validation_request(repository=REPOSITORY,issue_number=1762,branch=BRANCH,source_sha=SHA,validation_id="issue-scanner-proof")

def event(body):
 return {"action":"created","repository":{"full_name":REPOSITORY},"issue":{"number":1762},"comment":{"id":1,"body":body,"user":{"login":ACTOR}},"sender":{"login":ACTOR}}

def test_scanner_profile_is_one_fixed_existing_composition():
 profile=get_profile("issue-scanner-proof")
 assert profile.runner_kind is RunnerKind.ISSUE_SCANNER_PROOF
 assert profile.fixed_targets==("scripts/agent_os_github_issue_provider/scanner_proof.py",)
 assert profile_argv(profile.profile_id)==("python","-m","scripts.agent_os_github_issue_provider.scanner_proof")
 assert validation_argv(request())==profile_argv(profile.profile_id)

def test_scanner_ingress_accepts_only_exact_finite_identity():
 trigger=f"/agent-os dev-validate {BRANCH} {SHA} issue-scanner-proof"
 accepted=admit_issue_comment_event(event(trigger),expected_repository=REPOSITORY,allowed_actor=ACTOR,run_attempt=1)
 assert accepted.status=="accepted" and accepted.dev_validation_id_or_none=="issue-scanner-proof"
 for body in (trigger+" --repo other/repo",trigger+" ; echo nope",trigger.replace("issue-scanner-proof","issue-scanner-proof-extra")):
  result=admit_issue_comment_event(event(body),expected_repository=REPOSITORY,allowed_actor=ACTOR,run_attempt=1)
  assert (result.status,result.reason)==("ignored","malformed-trigger")

def test_scanner_host_route_is_fixed_to_credential_bridge():
 req=request();command=live._host_command(req);source=live._HOST_RUNNER_SOURCE
 assert live.SCANNER_PROOF_VALIDATION_ID in command
 assert "scripts.agent_os_github_issue_provider.scanner_proof" in command
 assert 'SCANNER_PROOF_ID="issue-scanner-proof"' in source
 assert 'SCANNER_PROOF_HOST_MODULE="scripts.agent_os_github_issue_provider.scanner_proof_host_bridge"' in source
 assert "scanner-proof-credential-injector-unavailable" not in source
 assert 'run((HOST_PYTHON,"-m",SCANNER_PROOF_HOST_MODULE)' in source
 assert "record_scanner_proof" in source
 assert "private_key" not in source and "Authorization" not in source and "GITHUB_TOKEN" not in source
 assert "sudo" not in command and "pip install" not in command

def test_scanner_profile_does_not_widen_legacy_registry_or_authority():
 req=request()
 assert live.SCANNER_PROOF_VALIDATION_ID not in live.VALIDATION_REGISTRY
 assert validation_argv(req)==live.SCANNER_PROOF_VALIDATION_ARGV
 payload=req.to_dict()
 assert not ({"argv","cwd","env","url","page","per_page","state","app_id","installation_id","secret_name"}&set(payload))
 assert payload["execution_authorized"] is False and payload["scheduler_invoked"] is False and payload["publication_invoked"] is False and payload["merge_authorized"] is False

def test_scanner_unavailable_evidence_is_bounded_and_non_authorizing():
 req=request()
 evidence={"schema_version":"1.0","status":"needs-decision","reason_codes":["scanner-proof-credential-injector-unavailable"],"repository":req.repository,"issue_number":req.issue_number,"branch":req.branch,"tested_sha":req.source_sha,"validation_id":req.validation_id,"request_id":req.request_id,"exit_code":0,"stdout_tail":"","stderr_tail":"","stdout_truncated":False,"stderr_truncated":False,"cleanup_complete":True,"workspace_side_effects_performed":True,"external_side_effects_performed":False,"production_state_mutated":False,"execution_authorized":False,"scheduler_invoked":False,"publication_invoked":False,"merge_authorized":False}
 framed=live._FRAME_START+"\n"+json.dumps(evidence)+"\n"+live._FRAME_END+"\n"
 adapter=SimpleNamespace(_ssh=lambda *_,**__:SimpleNamespace(returncode=0,stdout=framed,stderr=""))
 result=live.run_dev_validation_over_ssh(adapter,req)
 assert result["status"]=="needs-decision"
 assert result["reason_codes"]==["scanner-proof-credential-injector-unavailable"]
 assert result["stdout_tail"]==result["stderr_tail"]==""
 assert result["external_side_effects_performed"] is False and result["merge_authorized"] is False


def test_host_runner_source_is_syntactically_valid():
    compile(live._HOST_RUNNER_SOURCE, "<agent-os-dev-validation-host>", "exec")
