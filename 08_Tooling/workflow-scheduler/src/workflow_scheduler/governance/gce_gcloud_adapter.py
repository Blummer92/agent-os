"""Concrete bounded gcloud/IAP adapter for the #1217 GCE control path.

The adapter is intentionally narrow: one exact GCE tuple, IAP/OS Login SSH,
and fixed repository-owned operations. It has no arbitrary command API, no
retry loop for invocation, and no stop capability in the first activation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Mapping, Sequence

from .gce_control_path import FIXED_ENTRYPOINT, GceResourceTuple, HostInvocationEvidence, OidcTrustPolicy, VmState, run_gce_control_path, validate_handoff_id
from .github_issue_comment_ingress import IssueCommentIngressResult
from .governed_invocation_binding import bind_ingress_to_gce

PROJECT="agent-os-502614";ZONE="us-central1-a";INSTANCE="agent-os-test";RESOURCE=GceResourceTuple(project=PROJECT,zone=ZONE,instance=INSTANCE)
HOST_PYTHON="/usr/bin/python3";DISCOVERY_MODULE="agent_os_execution_service.handoff_discovery_entrypoint";DISCOVERY_PROBE_COMMAND=f"{HOST_PYTHON} -c 'import {DISCOVERY_MODULE}'";MAX_DIAGNOSTIC_STDERR=2048
WORKFLOW_REF="Blummer92/agent-os/.github/workflows/agent-os-governed-invocation.yml@refs/heads/main"
WIF_PROVIDER="//iam.googleapis.com/projects/966859826758/locations/global/workloadIdentityPools/agent-os-github/providers/agent-os-main"

# Fixed repository-owned sentinels framing the trusted runtime-inspection JSON.
# gcloud compute ssh can interleave its own local SSH-keygen chatter into the
# captured stdout stream (proven live in run 32896154122); these markers let
# the adapter isolate exactly the bytes the remote diagnostic itself printed
# instead of scanning for "{"/"}" in arbitrary transport noise.
_FRAME_START="===AGENT-OS-RUNTIME-INSPECTION-JSON-BEGIN==="
_FRAME_END="===AGENT-OS-RUNTIME-INSPECTION-JSON-END==="

_RUNTIME_INSPECTION_SOURCE=r'''import grp,importlib.util,json,os,pwd,site,stat,subprocess,sys,sysconfig
M="agent_os_execution_service.handoff_discovery_entrypoint"
def spec(n):
 try:
  s=importlib.util.find_spec(n);return None if s is None else {"origin":s.origin,"search_locations":list(s.submodule_search_locations or [])}
 except Exception as e:return {"error_class":type(e).__name__,"error":str(e)[:256]}
def meta(p):
 try:
  s=os.lstat(p);return {"path":p,"exists":True,"symlink":stat.S_ISLNK(s.st_mode),"owner":pwd.getpwuid(s.st_uid).pw_name,"group":grp.getgrgid(s.st_gid).gr_name,"mode":format(stat.S_IMODE(s.st_mode),"04o")}
 except FileNotFoundError:return {"path":p,"exists":False}
 except Exception as e:return {"path":p,"error_class":type(e).__name__}
def ancestors(p):
 out=[];q=os.path.abspath(p)
 while True:
  out.append(meta(q))
  if q=="/":break
  q=os.path.dirname(q)
 return list(reversed(out))
base=spec("agent_os_execution_service");sub=spec(M);paths=[]
if isinstance(base,dict):
 for p in base.get("search_locations",[]):paths.extend(ancestors(p))
probe=subprocess.run(["/usr/bin/python3","-c","import "+M],capture_output=True,text=True,check=False)
groups=[]
for g in os.getgroups():
 try:groups.append(grp.getgrgid(g).gr_name)
 except KeyError:groups.append(str(g))
out={"schema_version":"1.0","status":"observed","reason_codes":["runtime-context-observed"],"project":"agent-os-502614","zone":"us-central1-a","instance":"agent-os-test","interpreter":"/usr/bin/python3","effective_identity":{"username":pwd.getpwuid(os.geteuid()).pw_name,"uid":os.geteuid(),"gid":os.getegid(),"groups":groups},"python_context":{"version":sys.version.split()[0],"executable":sys.executable,"prefix":sys.prefix,"base_prefix":sys.base_prefix,"sys_path":sys.path,"site_packages":site.getsitepackages() if hasattr(site,"getsitepackages") else [],"user_site":site.getusersitepackages(),"purelib":sysconfig.get_path("purelib"),"platlib":sysconfig.get_path("platlib"),"pythonpath_set":"PYTHONPATH" in os.environ},"package_resolution":{"package":base,"submodule":sub},"filesystem_visibility":paths,"import_probe":{"exit_code":probe.returncode,"stderr":probe.stderr[-2048:],"stderr_truncated":len(probe.stderr)>2048},"execution_authorized":False,"scheduler_invoked":False,"discovery_invoked":False,"resume_invoked":False,"side_effects_performed":False}
'''+("print(%r);print(json.dumps(out,sort_keys=True,separators=(\",\",\":\")));print(%r)"%(_FRAME_START,_FRAME_END))
RUNTIME_INSPECTION_COMMAND=f"{HOST_PYTHON} -c {shlex.quote(_RUNTIME_INSPECTION_SOURCE)}"

class GcloudCommandError(RuntimeError):pass

def _run(argv:Sequence[str],*,timeout:int=60)->subprocess.CompletedProcess[str]:return subprocess.run(tuple(argv),check=False,capture_output=True,text=True,timeout=timeout)
def _require_ok(result:subprocess.CompletedProcess[str],operation:str)->str:
 if result.returncode!=0:raise GcloudCommandError(f"{operation} failed")
 return result.stdout.strip()
def _state(value:str)->VmState:return {"RUNNING":VmState.RUNNING,"TERMINATED":VmState.STOPPED,"STOPPED":VmState.STOPPED,"STAGING":VmState.STAGING,"STOPPING":VmState.STOPPING,"SUSPENDING":VmState.SUSPENDING}.get(value.strip().upper(),VmState.UNKNOWN)
def _discovery_command(*,repository:str,issue_number:int)->str:
 if repository!="Blummer92/agent-os":raise GcloudCommandError("non-canonical discovery repository rejected")
 if type(issue_number) is not int or issue_number<1:raise GcloudCommandError("non-canonical discovery issue rejected")
 return f"{HOST_PYTHON} -m {DISCOVERY_MODULE} --repository {repository} --issue-number {issue_number}"

class GcloudIapAdapter:
 def __init__(self,*,poll_seconds:float=2.0,max_polls:int=30)->None:
  if poll_seconds<=0 or max_polls<1:raise ValueError("poll bounds must be positive")
  self.poll_seconds=poll_seconds;self.max_polls=max_polls
 @staticmethod
 def _resource_args(resource:GceResourceTuple)->tuple[str,...]:
  if resource!=RESOURCE:raise GcloudCommandError("resource tuple is not the approved #1217 target")
  return ("--project",resource.project,"--zone",resource.zone)
 def observe_state(self,resource:GceResourceTuple)->VmState:return _state(_require_ok(_run(("gcloud","compute","instances","describe",resource.instance,*self._resource_args(resource),"--format=value(status)")),"observe instance state"))
 def start(self,resource:GceResourceTuple)->bool:return _run(("gcloud","compute","instances","start",resource.instance,*self._resource_args(resource),"--quiet"),timeout=120).returncode==0
 def wait_until_running(self,resource:GceResourceTuple)->VmState:
  for _ in range(self.max_polls):
   state=self.observe_state(resource)
   if state is VmState.RUNNING:return state
   if state not in {VmState.STAGING,VmState.STOPPED}:return state
   time.sleep(self.poll_seconds)
  return VmState.UNKNOWN
 def _ssh(self,resource:GceResourceTuple,command:str)->subprocess.CompletedProcess[str]:return _run(("gcloud","compute","ssh",resource.instance,*self._resource_args(resource),"--tunnel-through-iap","--quiet","--command",command),timeout=180)
 def probe_ready(self,resource:GceResourceTuple)->bool:return self._ssh(resource,f"test -x {FIXED_ENTRYPOINT}").returncode==0
 def probe_discovery_ready(self,resource:GceResourceTuple)->bool:return self._ssh(resource,DISCOVERY_PROBE_COMMAND).returncode==0
 def inspect_runtime(self,resource:GceResourceTuple)->dict[str,object]:
  result=self._ssh(resource,RUNTIME_INSPECTION_COMMAND)
  if result.returncode!=0:return _inspection_failure("needs-decision","inspection-command-failed",exit_code=result.returncode,stderr=result.stderr)
  framed,frame_reason=_extract_framed_payload(result.stdout)
  if framed is None:
   envelope=_inspection_failure("needs-decision",frame_reason,exit_code=result.returncode,stderr=result.stderr)
   envelope["stdout_evidence"]=_stdout_contamination_evidence(result.stdout)
   return envelope
  try:payload=json.loads(framed)
  except json.JSONDecodeError:
   envelope=_inspection_failure("needs-decision","inspection-evidence-not-json",exit_code=result.returncode,stderr=result.stderr)
   envelope["stdout_evidence"]=_stdout_contamination_evidence(result.stdout)
   return envelope
  if type(payload) is not dict:return _inspection_failure("needs-decision","inspection-evidence-malformed",exit_code=result.returncode,stderr=result.stderr)
  fixed={"project":PROJECT,"zone":ZONE,"instance":INSTANCE,"interpreter":HOST_PYTHON,"execution_authorized":False,"scheduler_invoked":False,"discovery_invoked":False,"resume_invoked":False,"side_effects_performed":False}
  if any(payload.get(k)!=v for k,v in fixed.items()):return _inspection_failure("needs-decision","inspection-contract-violation",exit_code=result.returncode,stderr=result.stderr)
  probe=payload.get("import_probe")
  if type(probe) is not dict or type(probe.get("stderr")) is not str:return _inspection_failure("needs-decision","inspection-contract-violation",exit_code=result.returncode,stderr=result.stderr)
  if len(probe["stderr"])>MAX_DIAGNOSTIC_STDERR:
   payload=dict(payload);payload["import_probe"]=dict(probe)
   payload["import_probe"]["stderr"]=probe["stderr"][-MAX_DIAGNOSTIC_STDERR:]
   payload["import_probe"]["stderr_truncated"]=True
  return payload
 def discover(self,resource:GceResourceTuple,*,repository:str,issue_number:int)->dict[str,object]:
  result=self._ssh(resource,_discovery_command(repository=repository,issue_number=issue_number))
  if result.returncode!=0:raise GcloudCommandError("fixed host discovery failed")
  try:payload=json.loads(result.stdout)
  except json.JSONDecodeError as exc:raise GcloudCommandError("host discovery evidence was not JSON") from exc
  if type(payload) is not dict:raise GcloudCommandError("host discovery evidence must be an object")
  if payload.get("repository")!=repository or payload.get("issue_number")!=issue_number:raise GcloudCommandError("host discovery identity mismatch")
  if payload.get("execution_authorized") is not False or payload.get("side_effects_performed") is not False:raise GcloudCommandError("discovery must remain read-only and non-authorizing")
  return payload
 def invoke(self,resource:GceResourceTuple,argv:tuple[str,...])->HostInvocationEvidence:
  if len(argv)!=3 or argv[0]!=FIXED_ENTRYPOINT or argv[1]!="--handoff-id":raise GcloudCommandError("non-canonical host argv rejected")
  if not validate_handoff_id(argv[2]):raise GcloudCommandError("non-canonical handoff id rejected")
  result=self._ssh(resource,f"{FIXED_ENTRYPOINT} --handoff-id {argv[2]}")
  if result.returncode!=0:raise GcloudCommandError("fixed host invocation failed")
  try:payload=json.loads(result.stdout)
  except json.JSONDecodeError as exc:raise GcloudCommandError("host evidence was not JSON") from exc
  if type(payload) is not dict:raise GcloudCommandError("host evidence must be an object")
  refs=payload.get("evidence_refs",())
  if type(refs) not in (list,tuple):raise GcloudCommandError("host evidence refs must be an array")
  return HostInvocationEvidence(invoked=True,accepted=payload.get("accepted") is True,scheduler_invocation_id=payload.get("scheduler_invocation_id"),execution_id=payload.get("execution_id"),terminal_status=payload.get("terminal_status"),termination_confirmed=payload.get("termination_confirmed") is True,lease_released=payload.get("lease_released") is True,cleanup_complete=payload.get("cleanup_complete") is True,retained_lease=payload.get("retained_lease") is True,quarantined=payload.get("quarantined") is True,evidence_refs=tuple(refs))
 def stop(self,resource:GceResourceTuple)->bool:return False

def _ingress_from_file(path:Path)->IssueCommentIngressResult:
 payload=json.loads(path.read_text(encoding="utf-8"))
 if type(payload) is not dict:raise ValueError("transport evidence must be an object")
 return IssueCommentIngressResult(**{key:payload[key] for key in ("schema_version","status","reason","repository","issue_number","comment_id","actor","handoff_id_or_none","logical_trigger_id_or_none","run_attempt")})
def _policy()->OidcTrustPolicy:return OidcTrustPolicy(repository="Blummer92/agent-os",repository_owner="Blummer92",workflow_ref=WORKFLOW_REF,ref="refs/heads/main",audience=WIF_PROVIDER)
def _non_authorizing(status:str,reason:str)->dict[str,object]:return {"schema_version":"1.0","status":status,"reason_codes":[reason],"project":PROJECT,"zone":ZONE,"instance":INSTANCE,"interpreter":HOST_PYTHON,"execution_authorized":False,"scheduler_invoked":False,"discovery_invoked":False,"resume_invoked":False,"side_effects_performed":False}
def _bounded_diagnostic_text(text:str)->tuple[str,bool]:
 if type(text) is not str:text=""
 if len(text)>MAX_DIAGNOSTIC_STDERR:return text[-MAX_DIAGNOSTIC_STDERR:],True
 return text,False
def _inspection_failure(status:str,reason:str,*,exit_code:int,stderr:str)->dict[str,object]:
 bounded_stderr,truncated=_bounded_diagnostic_text(stderr)
 envelope=_non_authorizing(status,reason)
 envelope["ssh_exit_code"]=exit_code
 envelope["ssh_stderr"]=bounded_stderr
 envelope["ssh_stderr_truncated"]=truncated
 return envelope

_STDOUT_EVIDENCE_PREFIX_CAP=200
_STDOUT_EVIDENCE_SUFFIX_CAP=200
_UNSAFE_SNIPPET_CHAR_RE=re.compile(r'[^\x09\x0a\x0d\x20-\x7e]')
def _sanitize_stdout_snippet(text:str)->str:return _UNSAFE_SNIPPET_CHAR_RE.sub("?",text)
def _stdout_contamination_evidence(stdout:str)->dict[str,object]:
 if type(stdout) is not str:stdout=""
 length=len(stdout)
 first_brace=stdout.find("{");last_brace=stdout.rfind("}")
 json_span_present=first_brace!=-1 and last_brace!=-1 and first_brace<last_brace
 return {
  "length":length,
  "empty":length==0,
  "json_object_span_present":json_span_present,
  "leading_text_before_json":json_span_present and first_brace>0,
  "trailing_text_after_json":json_span_present and last_brace<length-1,
  "prefix":_sanitize_stdout_snippet(stdout[:_STDOUT_EVIDENCE_PREFIX_CAP]),
  "prefix_truncated":length>_STDOUT_EVIDENCE_PREFIX_CAP,
  "suffix":_sanitize_stdout_snippet(stdout[-_STDOUT_EVIDENCE_SUFFIX_CAP:]) if length>_STDOUT_EVIDENCE_PREFIX_CAP else "",
  "suffix_truncated":length>_STDOUT_EVIDENCE_PREFIX_CAP+_STDOUT_EVIDENCE_SUFFIX_CAP,
  "sha256":hashlib.sha256(stdout.encode("utf-8",errors="replace")).hexdigest(),
 }

def _extract_framed_payload(stdout:str)->tuple[str|None,str|None]:
 """Return only the bytes between exactly one valid sentinel pair, or a fail-closed reason.

 Requires exactly one start marker and exactly one end marker, with the start
 strictly before the end. This is a structural boundary match on fixed
 repository-owned literals only -- it never scans for "{"/"}" and cannot be
 influenced by braces or any other content in surrounding transport chatter.
 """
 if type(stdout) is not str:stdout=""
 start_count=stdout.count(_FRAME_START)
 if start_count==0:return None,"inspection-frame-start-missing"
 if start_count>1:return None,"inspection-frame-start-duplicate"
 end_count=stdout.count(_FRAME_END)
 if end_count==0:return None,"inspection-frame-end-missing"
 if end_count>1:return None,"inspection-frame-end-duplicate"
 start_idx=stdout.find(_FRAME_START);end_idx=stdout.find(_FRAME_END)
 if end_idx<=start_idx:return None,"inspection-frame-order-invalid"
 return stdout[start_idx+len(_FRAME_START):end_idx].strip(),None

def execute_transport(ingress:IssueCommentIngressResult,*,claims:Mapping[str,object],adapter:GcloudIapAdapter)->dict[str,object]:
 if ingress.reason=="accepted-runtime-inspection-envelope":
  if ingress.status!="accepted" or ingress.issue_number is None:raise ValueError("runtime inspection requires accepted canonical issue evidence")
  if ingress.handoff_id_or_none is not None:raise ValueError("runtime inspection must not carry a handoff identity")
  if ingress.run_attempt!=1:raise ValueError("workflow reruns cannot perform runtime inspection")
  if not _policy().accepts(claims):return {"runtime_inspection":_non_authorizing("blocked","claims-rejected")}
  if adapter.observe_state(RESOURCE) is not VmState.RUNNING:return {"runtime_inspection":_non_authorizing("needs-decision","host-not-running")}
  return {"runtime_inspection":adapter.inspect_runtime(RESOURCE)}
 if ingress.reason=="accepted-discovery-envelope":
  if ingress.status!="accepted" or ingress.issue_number is None:raise ValueError("discovery requires accepted canonical issue evidence")
  if ingress.handoff_id_or_none is not None:raise ValueError("discovery must not carry a handoff identity")
  if ingress.run_attempt!=1:raise ValueError("workflow reruns cannot perform discovery")
  if not _policy().accepts(claims):return {"discovery":{"status":"blocked","reason_codes":["claims-rejected"],"repository":ingress.repository,"issue_number":ingress.issue_number,"handoff_id":None,"execution_authorized":False,"scheduler_invoked":False,"side_effects_performed":False}}
  initial=adapter.observe_state(RESOURCE)
  if initial is VmState.STOPPED:
   if not adapter.start(RESOURCE):return {"discovery":{"status":"needs-decision","reason_codes":["vm-start-failed"],"repository":ingress.repository,"issue_number":ingress.issue_number,"handoff_id":None,"execution_authorized":False,"scheduler_invoked":False,"side_effects_performed":False}}
   state=adapter.wait_until_running(RESOURCE)
  else:state=initial
  if state is not VmState.RUNNING:return {"discovery":{"status":"needs-decision","reason_codes":["host-unavailable"],"repository":ingress.repository,"issue_number":ingress.issue_number,"handoff_id":None,"execution_authorized":False,"scheduler_invoked":False,"side_effects_performed":False}}
  if not adapter.probe_discovery_ready(RESOURCE):return {"discovery":{"status":"needs-decision","reason_codes":["discovery-entrypoint-unavailable"],"repository":ingress.repository,"issue_number":ingress.issue_number,"handoff_id":None,"execution_authorized":False,"scheduler_invoked":False,"side_effects_performed":False}}
  return {"discovery":adapter.discover(RESOURCE,repository=ingress.repository,issue_number=ingress.issue_number)}
 binding=bind_ingress_to_gce(ingress,resource=RESOURCE);result=run_gce_control_path(request_id=binding.control_request_id,claims=claims,trust_policy=_policy(),resource=binding.resource,expected_resource=RESOURCE,handoff_id=binding.handoff_id,adapter=adapter,allow_shutdown=False)
 return {"binding":binding.to_dict(),"control":{"result_id":result.result_id,"status":result.status.value,"reason_codes":[item.value for item in result.reason_codes],"request_id":result.request_id,"handoff_id":result.handoff_id,"start_issued":result.start_issued,"host_ready":result.host_ready,"host_invoked":result.host_invoked,"host_accepted":result.host_accepted,"scheduler_invocation_id":result.scheduler_invocation_id,"execution_id":result.execution_id,"terminal_status":result.terminal_status,"shutdown_eligible":result.shutdown_eligible,"shutdown_issued":result.shutdown_issued,"retry_attempted":False,"github_writes_authorized":False,"merge_authorized":False}}

def main(argv:list[str]|None=None)->int:
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--transport",type=Path,required=True);parser.add_argument("--output",type=Path,required=True);parser.add_argument("--repository",required=True);parser.add_argument("--repository-owner",required=True);parser.add_argument("--workflow-ref",required=True);parser.add_argument("--ref",required=True);parser.add_argument("--audience",required=True);args=parser.parse_args(argv)
 claims={"repository":args.repository,"repository_owner":args.repository_owner,"workflow_ref":args.workflow_ref,"ref":args.ref,"aud":args.audience};evidence=execute_transport(_ingress_from_file(args.transport),claims=claims,adapter=GcloudIapAdapter());args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(evidence,sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8");print(json.dumps(evidence,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
