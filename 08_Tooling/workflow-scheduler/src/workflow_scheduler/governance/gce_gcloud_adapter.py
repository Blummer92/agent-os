"""Concrete bounded gcloud/IAP adapter for the #1217 GCE control path.

Only fixed repository-owned operations are admitted. There is no arbitrary
command API, retry loop, provider fallback, or VM stop capability.
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

PROJECT="agent-os-502614"; ZONE="us-central1-a"; INSTANCE="agent-os-test"; RESOURCE=GceResourceTuple(project=PROJECT,zone=ZONE,instance=INSTANCE)
HOST_PYTHON="/usr/bin/python3"
DISCOVERY_MODULE="agent_os_execution_service.handoff_discovery_entrypoint"
ACTIVATION_MODULE="agent_os_execution_service.first_publication_activation_entrypoint"
DISCOVERY_PROBE_COMMAND=f"{HOST_PYTHON} -c 'import {DISCOVERY_MODULE}'"
ACTIVATION_PROBE_COMMAND=f"{HOST_PYTHON} -c 'import {ACTIVATION_MODULE}'"
MAX_DIAGNOSTIC_STDERR=2048
WORKFLOW_REF="Blummer92/agent-os/.github/workflows/agent-os-governed-invocation.yml@refs/heads/main"
WIF_PROVIDER="//iam.googleapis.com/projects/966859826758/locations/global/workloadIdentityPools/agent-os-github/providers/agent-os-main"
_FRAME_START="===AGENT-OS-RUNTIME-INSPECTION-JSON-BEGIN==="; _FRAME_END="===AGENT-OS-RUNTIME-INSPECTION-JSON-END==="
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

class GcloudCommandError(RuntimeError): pass

def _run(argv:Sequence[str],*,timeout:int=60)->subprocess.CompletedProcess[str]: return subprocess.run(tuple(argv),check=False,capture_output=True,text=True,timeout=timeout)
def _require_ok(result:subprocess.CompletedProcess[str],operation:str)->str:
 if result.returncode!=0: raise GcloudCommandError(f"{operation} failed")
 return result.stdout.strip()
def _state(value:str)->VmState: return {"RUNNING":VmState.RUNNING,"TERMINATED":VmState.STOPPED,"STOPPED":VmState.STOPPED,"STAGING":VmState.STAGING,"STOPPING":VmState.STOPPING,"SUSPENDING":VmState.SUSPENDING}.get(value.strip().upper(),VmState.UNKNOWN)
def _discovery_command(*,repository:str,issue_number:int)->str:
 if repository!="Blummer92/agent-os" or type(issue_number) is not int or issue_number<1: raise GcloudCommandError("non-canonical discovery identity rejected")
 return f"{HOST_PYTHON} -m {DISCOVERY_MODULE} --repository {repository} --issue-number {issue_number}"
def _activation_command(capsule:str)->str:
 if not re.fullmatch(r"pre-publication-evidence:[0-9a-f]{64}",capsule): raise GcloudCommandError("non-canonical source capsule rejected")
 return f"{HOST_PYTHON} -m {ACTIVATION_MODULE} --source-capsule-id {capsule}"

class GcloudIapAdapter:
 def __init__(self,*,poll_seconds:float=2.0,max_polls:int=30)->None:
  if poll_seconds<=0 or max_polls<1: raise ValueError("poll bounds must be positive")
  self.poll_seconds=poll_seconds; self.max_polls=max_polls
 @staticmethod
 def _resource_args(resource:GceResourceTuple)->tuple[str,...]:
  if resource!=RESOURCE: raise GcloudCommandError("resource tuple is not the approved #1217 target")
  return ("--project",resource.project,"--zone",resource.zone)
 def observe_state(self,resource:GceResourceTuple)->VmState: return _state(_require_ok(_run(("gcloud","compute","instances","describe",resource.instance,*self._resource_args(resource),"--format=value(status)")),"observe instance state"))
 def start(self,resource:GceResourceTuple)->bool: return _run(("gcloud","compute","instances","start",resource.instance,*self._resource_args(resource),"--quiet"),timeout=120).returncode==0
 def wait_until_running(self,resource:GceResourceTuple)->VmState:
  for _ in range(self.max_polls):
   state=self.observe_state(resource)
   if state is VmState.RUNNING:return state
   if state not in {VmState.STAGING,VmState.STOPPED}:return state
   time.sleep(self.poll_seconds)
  return VmState.UNKNOWN
 def _ssh(self,resource:GceResourceTuple,command:str)->subprocess.CompletedProcess[str]: return _run(("gcloud","compute","ssh",resource.instance,*self._resource_args(resource),"--tunnel-through-iap","--quiet","--command",command),timeout=180)
 def probe_ready(self,resource:GceResourceTuple)->bool:return self._ssh(resource,f"test -x {FIXED_ENTRYPOINT}").returncode==0
 def probe_discovery_ready(self,resource:GceResourceTuple)->bool:return self._ssh(resource,DISCOVERY_PROBE_COMMAND).returncode==0
 def probe_activation_ready(self,resource:GceResourceTuple)->bool:return self._ssh(resource,ACTIVATION_PROBE_COMMAND).returncode==0
 def activate_first_publication(self,resource:GceResourceTuple,*,source_capsule_id:str)->dict[str,object]:
  result=self._ssh(resource,_activation_command(source_capsule_id))
  if result.returncode!=0: raise GcloudCommandError("fixed first-publication activation failed")
  try: payload=json.loads(result.stdout)
  except json.JSONDecodeError as exc: raise GcloudCommandError("activation evidence was not JSON") from exc
  if type(payload) is not dict or payload.get("source_capsule_id")!=source_capsule_id: raise GcloudCommandError("activation evidence identity mismatch")
  if payload.get("scheduler_invoked") is not False or payload.get("execution_lease_acquired") is not False or payload.get("resume_invoked") is not False: raise GcloudCommandError("activation crossed execution boundary")
  return payload
 def inspect_runtime(self,resource:GceResourceTuple)->dict[str,object]:
  result=self._ssh(resource,RUNTIME_INSPECTION_COMMAND)
  if result.returncode!=0:return _inspection_failure("needs-decision","inspection-command-failed",exit_code=result.returncode,stderr=result.stderr)
  framed,reason=_extract_framed_payload(result.stdout)
  if framed is None:return _inspection_failure("needs-decision",reason,exit_code=result.returncode,stderr=result.stderr)
  try:payload=json.loads(framed)
  except json.JSONDecodeError:return _inspection_failure("needs-decision","inspection-evidence-not-json",exit_code=result.returncode,stderr=result.stderr)
  if type(payload) is not dict:return _inspection_failure("needs-decision","inspection-evidence-malformed",exit_code=result.returncode,stderr=result.stderr)
  fixed={"project":PROJECT,"zone":ZONE,"instance":INSTANCE,"interpreter":HOST_PYTHON,"execution_authorized":False,"scheduler_invoked":False,"discovery_invoked":False,"resume_invoked":False,"side_effects_performed":False}
  if any(payload.get(k)!=v for k,v in fixed.items()):return _inspection_failure("needs-decision","inspection-contract-violation",exit_code=result.returncode,stderr=result.stderr)
  return payload
 def discover(self,resource:GceResourceTuple,*,repository:str,issue_number:int)->dict[str,object]:
  result=self._ssh(resource,_discovery_command(repository=repository,issue_number=issue_number))
  if result.returncode!=0:raise GcloudCommandError("fixed host discovery failed")
  try:payload=json.loads(result.stdout)
  except json.JSONDecodeError as exc:raise GcloudCommandError("host discovery evidence was not JSON") from exc
  if type(payload) is not dict or payload.get("repository")!=repository or payload.get("issue_number")!=issue_number:raise GcloudCommandError("host discovery identity mismatch")
  if payload.get("execution_authorized") is not False or payload.get("side_effects_performed") is not False:raise GcloudCommandError("discovery must remain read-only")
  return payload
 def invoke(self,resource:GceResourceTuple,argv:tuple[str,...])->HostInvocationEvidence:
  if len(argv)!=3 or argv[0]!=FIXED_ENTRYPOINT or argv[1]!="--handoff-id" or not validate_handoff_id(argv[2]):raise GcloudCommandError("non-canonical host argv rejected")
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
 values={key:payload[key] for key in ("schema_version","status","reason","repository","issue_number","comment_id","actor","handoff_id_or_none","logical_trigger_id_or_none","run_attempt")}
 for key in ("dev_validation_branch_or_none","dev_validation_sha_or_none","dev_validation_id_or_none","source_capsule_id_or_none"):values[key]=payload.get(key)
 return IssueCommentIngressResult(**values)
def _policy()->OidcTrustPolicy:return OidcTrustPolicy(repository="Blummer92/agent-os",repository_owner="Blummer92",workflow_ref=WORKFLOW_REF,ref="refs/heads/main",audience=WIF_PROVIDER)
def _non_authorizing(status:str,reason:str)->dict[str,object]:return {"schema_version":"1.0","status":status,"reason_codes":[reason],"project":PROJECT,"zone":ZONE,"instance":INSTANCE,"interpreter":HOST_PYTHON,"execution_authorized":False,"scheduler_invoked":False,"discovery_invoked":False,"resume_invoked":False,"side_effects_performed":False}
def _bounded_diagnostic_text(text:str)->tuple[str,bool]:
 if type(text) is not str:text=""
 return (text[-MAX_DIAGNOSTIC_STDERR:],True) if len(text)>MAX_DIAGNOSTIC_STDERR else (text,False)
def _inspection_failure(status:str,reason:str,*,exit_code:int,stderr:str)->dict[str,object]:
 bounded,truncated=_bounded_diagnostic_text(stderr);out=_non_authorizing(status,reason);out.update({"ssh_exit_code":exit_code,"ssh_stderr":bounded,"ssh_stderr_truncated":truncated});return out

def _extract_framed_payload(stdout:str)->tuple[str|None,str|None]:
 if type(stdout) is not str:stdout=""
 if stdout.count(_FRAME_START)!=1:return None,"inspection-frame-start-missing" if _FRAME_START not in stdout else "inspection-frame-start-duplicate"
 if stdout.count(_FRAME_END)!=1:return None,"inspection-frame-end-missing" if _FRAME_END not in stdout else "inspection-frame-end-duplicate"
 start=stdout.find(_FRAME_START);end=stdout.find(_FRAME_END)
 if end<=start:return None,"inspection-frame-order-invalid"
 return stdout[start+len(_FRAME_START):end].strip(),None

def execute_transport(ingress:IssueCommentIngressResult,*,claims:Mapping[str,object],adapter:GcloudIapAdapter)->dict[str,object]:
 if ingress.reason=="accepted-dev-validation-envelope":
  from .dev_validation_gce import execute_dev_validation_transport
  return execute_dev_validation_transport(ingress,claims=claims,adapter=adapter)
 if ingress.reason=="accepted-runtime-inspection-envelope":
  if ingress.status!="accepted" or ingress.issue_number is None:raise ValueError("runtime inspection requires accepted canonical issue evidence")
  if ingress.handoff_id_or_none is not None or ingress.run_attempt!=1:raise ValueError("runtime inspection transport malformed")
  if not _policy().accepts(claims):return {"runtime_inspection":_non_authorizing("blocked","claims-rejected")}
  if adapter.observe_state(RESOURCE) is not VmState.RUNNING:return {"runtime_inspection":_non_authorizing("needs-decision","host-not-running")}
  from .cloud_identity_inspection import collect_cloud_identity
  return {"runtime_inspection":adapter.inspect_runtime(RESOURCE),"cloud_identity":collect_cloud_identity(_run)}
 if ingress.reason=="accepted-first-publication-activation-envelope":
  if ingress.status!="accepted" or ingress.issue_number is None or ingress.source_capsule_id_or_none is None:raise ValueError("activation requires accepted canonical source capsule evidence")
  if ingress.handoff_id_or_none is not None or ingress.run_attempt!=1:raise ValueError("activation transport malformed")
  if not _policy().accepts(claims):return {"first_publication_activation":_non_authorizing("blocked","claims-rejected")}
  state=adapter.observe_state(RESOURCE)
  if state is not VmState.RUNNING:return {"first_publication_activation":_non_authorizing("needs-decision","host-not-running")}
  if not adapter.probe_activation_ready(RESOURCE):return {"first_publication_activation":_non_authorizing("needs-decision","activation-entrypoint-unavailable")}
  return {"first_publication_activation":adapter.activate_first_publication(RESOURCE,source_capsule_id=ingress.source_capsule_id_or_none)}
 if ingress.reason=="accepted-discovery-envelope":
  if ingress.status!="accepted" or ingress.issue_number is None:raise ValueError("discovery requires accepted canonical issue evidence")
  if ingress.handoff_id_or_none is not None or ingress.run_attempt!=1:raise ValueError("discovery transport malformed")
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
