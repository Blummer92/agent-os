"""Bounded read-only Codespaces diagnostics for #2947.

This module reuses the already-approved Codespaces identity and SSH transport from
#2931. It accepts only the finite diagnostic identity admitted by the canonical
issue-comment ingress. It never exposes caller-provided shell, argv, URLs, paths,
or lifecycle mutation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .dev_validation import REPOSITORY
from .dev_validation_codespaces import (
    APPROVED_CODESPACE_PROFILE_ID,
    _CODESPACE_NAME_RE,
    _bounded_text,
    _run,
    resolve_current_codespace,
    surface_id,
)
from .github_issue_comment_ingress import IssueCommentIngressResult

DIAGNOSTIC_ID = "ppux-canva-cdp-readonly"
ADOBE_DIAGNOSTIC_ID = "ppux-adobe-minimum-probe"
ADOBE_EXPRESS_URL = "https://new.express.adobe.com/"
DIAGNOSTIC_IDS = frozenset({DIAGNOSTIC_ID, ADOBE_DIAGNOSTIC_ID})
DIAGNOSTIC_REASON = "accepted-codespaces-diagnostic-envelope"
_FRAME_START = "===AGENT-OS-CODESPACES-DIAGNOSTIC-JSON-BEGIN==="
_FRAME_END = "===AGENT-OS-CODESPACES-DIAGNOSTIC-JSON-END==="
_RUN_TIMEOUT_SECONDS = 90
_REQUEST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$", re.ASCII)

_REMOTE_RUNNER_SOURCE = r'''import json,os,re,socket,subprocess,sys,urllib.request
PROFILE_ID="agent-os-codespaces-v1"
DIAGNOSTIC_ID="ppux-canva-cdp-readonly"
FRAME_START="===AGENT-OS-CODESPACES-DIAGNOSTIC-JSON-BEGIN==="
FRAME_END="===AGENT-OS-CODESPACES-DIAGNOSTIC-JSON-END==="
REQ=re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$",re.ASCII)

def run(argv,*,cwd=None,timeout=20):
 return subprocess.run(tuple(argv),cwd=cwd,check=False,capture_output=True,text=True,timeout=timeout)

def emit(payload):
 print(FRAME_START);print(json.dumps(payload,sort_keys=True,separators=(",",":")));print(FRAME_END)

def base(status,reason,issue,request_id,codespace_name):
 return {"schema_version":"1.0","status":status,"reason_codes":[reason],"repository":"Blummer92/agent-os","issue_number":issue,"diagnostic_id":DIAGNOSTIC_ID,"request_id":request_id,"codespace_name":codespace_name,"codespaces_profile_id":PROFILE_ID,"execution_surface_id":f"codespace:{codespace_name}","environment_health_evidence_id":None,"workspace_head":None,"workspace_branch":None,"chrome_process_count":None,"loopback":{"9222":False,"9444":False},"cdp":{"browser":None,"target_count":0,"targets":[]},"cleanup_complete":True,"workspace_side_effects_performed":False,"external_side_effects_performed":False,"production_state_mutated":False,"execution_authorized":False,"scheduler_invoked":False,"publication_invoked":False,"merge_authorized":False}

if len(sys.argv)!=5:
 emit(base("needs-decision","invalid-codespaces-diagnostic-argv",0,"unavailable","unavailable"));raise SystemExit(0)
issue_text,diagnostic_id,request_id,codespace_name=sys.argv[1:]
try: issue=int(issue_text)
except ValueError: issue=0
result=base("needs-decision","codespaces-diagnostic-failed",issue,request_id,codespace_name)
if issue<1 or diagnostic_id!=DIAGNOSTIC_ID or REQ.fullmatch(request_id) is None:
 result["reason_codes"]=["invalid-codespaces-diagnostic-identity"];emit(result);raise SystemExit(0)
if os.environ.get("CODESPACE_NAME")!=codespace_name:
 result["reason_codes"]=["codespaces-surface-identity-mismatch"];emit(result);raise SystemExit(0)
primary="/workspaces/agent-os"
if not os.path.isdir(primary):
 result["reason_codes"]=["codespaces-workspace-unavailable"];emit(result);raise SystemExit(0)

health=run(("python3","scripts/agent-os-environment-health.py","--execution-surface-id",f"codespace:{codespace_name}"),cwd=primary,timeout=20)
try: health_payload=json.loads(health.stdout)
except json.JSONDecodeError: health_payload={}
authority=health_payload.get("authority") if isinstance(health_payload,dict) else None
safe_authority=isinstance(authority,dict) and authority and all(value is False for value in authority.values())
if health.returncode!=0 or health_payload.get("status")!="pass" or health_payload.get("profile_id")!=PROFILE_ID or health_payload.get("execution_surface_id")!=f"codespace:{codespace_name}" or not safe_authority:
 result["reason_codes"]=["codespaces-environment-health-invalid"];emit(result);raise SystemExit(0)
result["environment_health_evidence_id"]=health_payload.get("environment_health_evidence_id")

head=run(("git","rev-parse","HEAD"),cwd=primary,timeout=10)
branch=run(("git","branch","--show-current"),cwd=primary,timeout=10)
if head.returncode==0: result["workspace_head"]=head.stdout.strip()[:40]
if branch.returncode==0: result["workspace_branch"]=branch.stdout.strip()[:180]

pgrep=run(("pgrep","-c","chrome"),cwd=primary,timeout=10)
if pgrep.returncode in (0,1):
 try: result["chrome_process_count"]=int((pgrep.stdout or "0").strip() or "0")
 except ValueError: pass

def loopback(port):
 try:
  with socket.create_connection(("127.0.0.1",port),timeout=1): return True
 except OSError: return False

result["loopback"]={"9222":loopback(9222),"9444":loopback(9444)}

def get_json(url):
 with urllib.request.urlopen(url,timeout=2) as response:
  raw=response.read(262144)
 return json.loads(raw.decode("utf-8"))

if result["loopback"]["9222"]:
 try:
  version=get_json("http://127.0.0.1:9222/json/version")
  result["cdp"]["browser"]={
   "product":version.get("Browser") if isinstance(version,dict) else None,
   "protocol_version":version.get("Protocol-Version") if isinstance(version,dict) else None,
   "headless":bool(isinstance(version,dict) and "HeadlessChrome/" in str(version.get("User-Agent",""))),
  }
 except Exception:
  result["cdp"]["browser"]={"error":"version-unavailable"}
 try:
  targets=get_json("http://127.0.0.1:9222/json")
  if isinstance(targets,list):
   bounded=[]
   for item in targets[:12]:
    if not isinstance(item,dict): continue
    title=str(item.get("title",""))
    title_class="home-canva" if title=="Home - Canva" else ("canva" if "canva" in title.lower() else "other")
    url=str(item.get("url",""))
    origin="canva.com" if "canva.com" in url else ("chrome-ui" if url.startswith("chrome://") else "other")
    bounded.append({"id":str(item.get("id",""))[:64],"type":str(item.get("type",""))[:32],"title_class":title_class,"origin":origin,"websocket_present":isinstance(item.get("webSocketDebuggerUrl"),str)})
   result["cdp"]["target_count"]=len(targets)
   result["cdp"]["targets"]=bounded
 except Exception:
  result["cdp"]["targets"]=[{"error":"targets-unavailable"}]

result["status"]="success"
result["reason_codes"]=["diagnostic-observed"]
emit(result)
'''

Run = Callable[..., subprocess.CompletedProcess[str]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _attach_invocation_metadata(
    evidence: dict[str, object],
    *,
    started_at: str,
) -> dict[str, object]:
    run_id = os.environ.get("GITHUB_RUN_ID")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
    safe_run_id = int(run_id) if type(run_id) is str and run_id.isdigit() else None
    safe_attempt = (
        int(run_attempt)
        if type(run_attempt) is str and run_attempt.isdigit()
        else None
    )
    evidence.update(
        {
            "started_at": started_at,
            "finished_at": _utc_now(),
            "workflow_run_id": safe_run_id,
            "workflow_run_attempt": safe_attempt,
            "workflow_name": "Agent OS Governed Invocation Ingress",
            "workflow_job_name": "Validate and transport bounded Agent OS invocation",
            "artifact_name": (
                f"agent-os-ingress-{safe_run_id}-{safe_attempt}"
                if safe_run_id is not None and safe_attempt is not None
                else None
            ),
        }
    )
    return evidence


@dataclass(frozen=True, slots=True)
class CodespacesDiagnosticRequest:
    repository: str
    issue_number: int
    diagnostic_id: str
    request_id: str


def _route(
    *,
    handled: bool,
    selected: bool,
    reason: str,
    state: str | None = None,
    codespace_name: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "handled": handled,
        "selected": selected,
        "reason_codes": [reason],
        "codespace_name": codespace_name,
        "codespaces_profile_id": APPROVED_CODESPACE_PROFILE_ID,
        "execution_surface_id": surface_id(codespace_name),
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
) -> CodespacesDiagnosticRequest:
    if ingress.status != "accepted" or ingress.reason != DIAGNOSTIC_REASON:
        raise ValueError("diagnostic requires accepted canonical ingress evidence")
    if ingress.run_attempt != 1:
        raise ValueError("workflow reruns cannot perform diagnostics")
    if ingress.issue_number is None:
        raise ValueError("diagnostic issue identity missing")
    diagnostic_id = ingress.diagnostic_id_or_none
    request_id = ingress.diagnostic_request_id_or_none
    if diagnostic_id not in DIAGNOSTIC_IDS:
        raise ValueError("diagnostic identity is not approved")
    if type(request_id) is not str or _REQUEST_ID_RE.fullmatch(request_id) is None:
        raise ValueError("diagnostic request identity is invalid")
    return CodespacesDiagnosticRequest(
        repository=ingress.repository,
        issue_number=ingress.issue_number,
        diagnostic_id=diagnostic_id,
        request_id=request_id,
    )


def _failure(
    request: CodespacesDiagnosticRequest,
    reason: str,
    codespace_name: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": "needs-decision",
        "reason_codes": [reason],
        "repository": request.repository,
        "issue_number": request.issue_number,
        "diagnostic_id": request.diagnostic_id,
        "request_id": request.request_id,
        "codespace_name": codespace_name,
        "codespaces_profile_id": APPROVED_CODESPACE_PROFILE_ID,
        "execution_surface_id": surface_id(codespace_name),
        "environment_health_evidence_id": None,
        "cleanup_complete": True,
        "workspace_side_effects_performed": False,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }


def select_codespaces_diagnostic(
    ingress: IssueCommentIngressResult,
    *,
    run: Run = _run,
) -> tuple[dict[str, object], CodespacesDiagnosticRequest | None]:
    if ingress.status != "accepted" or ingress.reason != DIAGNOSTIC_REASON:
        return _route(handled=False, selected=False, reason="not-codespaces-diagnostic"), None

    request = _request_from_ingress(ingress)
    selection = resolve_current_codespace(run)
    return (
        _route(
            handled=True,
            selected=selection.selected,
            reason=selection.reason,
            state=selection.state,
            codespace_name=selection.codespace_name,
        ),
        request,
    )


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


_ADOBE_REMOTE_RUNNER_SOURCE = r'''import json,os,platform,re,shutil,subprocess,sys
PROFILE_ID="agent-os-codespaces-v1"
DIAGNOSTIC_ID="ppux-adobe-minimum-probe"
ADOBE_URL="https://new.express.adobe.com/"
FRAME_START="===AGENT-OS-CODESPACES-DIAGNOSTIC-JSON-BEGIN==="
FRAME_END="===AGENT-OS-CODESPACES-DIAGNOSTIC-JSON-END==="
REQ=re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$",re.ASCII)
SAFE=re.compile(r"(?i)(cookie|token|password|secret|authorization|profile)")
MAX_TEXT=240

def run(argv,*,cwd=None,timeout=20):
 return subprocess.run(tuple(argv),cwd=cwd,check=False,capture_output=True,text=True,timeout=timeout)

def emit(payload):
 print(FRAME_START);print(json.dumps(payload,sort_keys=True,separators=(",",":")));print(FRAME_END)

def text(value,limit=MAX_TEXT):
 value=str(value or "").replace("\r"," ").replace("\n"," ").strip()
 return value[:limit] if not SAFE.search(value) else "[redacted]"

def base(status,reason,issue,request_id,codespace_name):
 return {"schema_version":"1.0","status":status,"reason_codes":[reason],"disposition":"MANUAL_REVIEW","repository":"Blummer92/agent-os","issue_number":issue,"diagnostic_id":DIAGNOSTIC_ID,"request_id":request_id,"codespace_name":codespace_name,"codespaces_profile_id":PROFILE_ID,"execution_surface_id":f"codespace:{codespace_name}","environment_health_evidence_id":None,"workspace_head":None,"workspace_branch":None,"os_distribution":None,"kernel":None,"cpu_architecture":None,"cpu_count":os.cpu_count(),"ram_bytes":None,"available_disk_bytes":None,"browser_executable":None,"browser_version":None,"display_mode":"headless","graphics_renderer":None,"webgl":"unknown","webgl2":"unknown","requested_url":ADOBE_URL,"final_url":None,"network_application_reachability":"unknown","page_title":None,"browser_process_exit_classification":"not-started","redirect_classification":"unknown","unsupported_browser_detected":False,"unsupported_system_detected":False,"normal_login_or_application_surface_detected":False,"fatal_browser_error":None,"fatal_renderer_error":None,"cleanup_complete":False,"workspace_side_effects_performed":False,"external_side_effects_performed":False,"production_state_mutated":False,"execution_authorized":False,"scheduler_invoked":False,"publication_invoked":False,"merge_authorized":False}

if len(sys.argv)!=5:
 emit(base("needs-decision","invalid-codespaces-diagnostic-argv",0,"unavailable","unavailable"));raise SystemExit(0)
issue_text,diagnostic_id,request_id,codespace_name=sys.argv[1:]
try: issue=int(issue_text)
except ValueError: issue=0
result=base("needs-decision","codespaces-diagnostic-failed",issue,request_id,codespace_name)
if issue<1 or diagnostic_id!=DIAGNOSTIC_ID or REQ.fullmatch(request_id) is None:
 result["reason_codes"]=["invalid-codespaces-diagnostic-identity"];result["cleanup_complete"]=True;emit(result);raise SystemExit(0)
if os.environ.get("CODESPACE_NAME")!=codespace_name:
 result["reason_codes"]=["codespaces-surface-identity-mismatch"];result["cleanup_complete"]=True;emit(result);raise SystemExit(0)
primary="/workspaces/agent-os"
if not os.path.isdir(primary):
 result["reason_codes"]=["codespaces-workspace-unavailable"];result["cleanup_complete"]=True;emit(result);raise SystemExit(0)

health=run(("python3","scripts/agent-os-environment-health.py","--execution-surface-id",f"codespace:{codespace_name}"),cwd=primary,timeout=20)
try: health_payload=json.loads(health.stdout)
except Exception: health_payload={}
authority=health_payload.get("authority") if isinstance(health_payload,dict) else None
safe_authority=isinstance(authority,dict) and authority and all(value is False for value in authority.values())
if health.returncode!=0 or health_payload.get("status")!="pass" or health_payload.get("profile_id")!=PROFILE_ID or health_payload.get("execution_surface_id")!=f"codespace:{codespace_name}" or not safe_authority:
 result["reason_codes"]=["codespaces-environment-health-invalid"];result["cleanup_complete"]=True;emit(result);raise SystemExit(0)
result["environment_health_evidence_id"]=health_payload.get("environment_health_evidence_id")

head=run(("git","rev-parse","HEAD"),cwd=primary,timeout=10);branch=run(("git","branch","--show-current"),cwd=primary,timeout=10)
if head.returncode==0:result["workspace_head"]=text(head.stdout,40)
if branch.returncode==0:result["workspace_branch"]=text(branch.stdout,180)
result["os_distribution"]=text(" ".join(platform.freedesktop_os_release().get(k,"") for k in ("NAME","VERSION_ID")))
result["kernel"]=text(platform.release());result["cpu_architecture"]=text(platform.machine(),80)
try:
 pages=os.sysconf("SC_PHYS_PAGES");page_size=os.sysconf("SC_PAGE_SIZE");result["ram_bytes"]=int(pages*page_size)
except (ValueError,OSError,AttributeError):pass
try:result["available_disk_bytes"]=int(shutil.disk_usage(primary).free)
except OSError:pass

browser=next((p for p in ("google-chrome","google-chrome-stable","chromium","chromium-browser") if shutil.which(p)),None)
if browser is None:
 result["reason_codes"]=["adobe-browser-unavailable"];result["disposition"]="CODESPACES_EXECUTION_PATH_BLOCKED";result["cleanup_complete"]=True;emit(result);raise SystemExit(0)
result["browser_executable"]=browser
version=run((browser,"--version"),timeout=10)
if version.returncode==0:result["browser_version"]=text(version.stdout,160)

js="""const { chromium } = require('playwright'); (async()=>{let b;try{b=await chromium.launch({headless:true,executablePath:process.argv[1]});const p=await b.newPage();let response=null;try{response=await p.goto(process.argv[2],{waitUntil:'domcontentloaded',timeout:30000});}catch(e){}const finalUrl=p.url();const title=(await p.title()).slice(0,240);const gpu=await p.evaluate(()=>{const c=document.createElement('canvas');const g2=c.getContext('webgl2');const g=c.getContext('webgl')||c.getContext('experimental-webgl');let renderer=null;try{const x=g2||g;if(x){const d=x.getExtension('WEBGL_debug_renderer_info');if(d)renderer=x.getParameter(d.UNMASKED_RENDERER_WEBGL);}}catch(e){}return {webgl:!!g,webgl2:!!g2,renderer};});console.log(JSON.stringify({ok:true,status:response?response.status():null,finalUrl,title,...gpu}));}catch(e){console.log(JSON.stringify({ok:false,error:String(e).slice(0,240)}));}finally{if(b)await b.close();}})();"""
probe=run(("node","-e",js,browser,ADOBE_URL),cwd=primary,timeout=45)
result["browser_process_exit_classification"]="exit-0" if probe.returncode==0 else f"exit-{probe.returncode}"
try: observed=json.loads((probe.stdout or "").strip().splitlines()[-1])
except Exception: observed={}
if not isinstance(observed,dict) or not observed.get("ok"):
 result["reason_codes"]=["adobe-browser-probe-failed"];result["disposition"]="CODESPACES_EXECUTION_PATH_BLOCKED";result["fatal_browser_error"]=text(observed.get("error") if isinstance(observed,dict) else None);result["cleanup_complete"]=True;emit(result);raise SystemExit(0)

final_url=text(observed.get("finalUrl"),500);title=text(observed.get("title"))
result["final_url"]=final_url;result["page_title"]=title
result["network_application_reachability"]="reachable" if observed.get("status") is not None or final_url else "unknown"
result["graphics_renderer"]=text(observed.get("renderer"),240)
result["webgl"]="yes" if observed.get("webgl") is True else ("no" if observed.get("webgl") is False else "unknown")
result["webgl2"]="yes" if observed.get("webgl2") is True else ("no" if observed.get("webgl2") is False else "unknown")
lower=(final_url+" "+title).lower()
unsupported_browser="/unsupported-browser" in lower or "unsupported browser" in lower
unsupported_system="unsupported system" in lower or "system requirements" in lower
result["unsupported_browser_detected"]=unsupported_browser;result["unsupported_system_detected"]=unsupported_system
if final_url and final_url!=ADOBE_URL:result["redirect_classification"]="same-adobe" if "adobe.com" in final_url.lower() else "other-origin"
else:result["redirect_classification"]="none"
normal=bool(final_url and "adobe.com" in final_url.lower() and not unsupported_browser and not unsupported_system)
result["normal_login_or_application_surface_detected"]=normal
if unsupported_browser or unsupported_system:
 result["status"]="success";result["reason_codes"]=["adobe-unsupported-platform-observed"];result["disposition"]="CODESPACES_BLOCKED_UNSUPPORTED_PLATFORM"
elif observed.get("webgl") is False and observed.get("webgl2") is False:
 result["status"]="success";result["reason_codes"]=["adobe-graphics-blocked"];result["disposition"]="CODESPACES_BLOCKED_GRAPHICS"
elif normal:
 result["status"]="success";result["reason_codes"]=["adobe-minimum-probe-passed"];result["disposition"]="CODESPACES_ADOBE_MINIMUM_PROBE_PASS"
elif result["network_application_reachability"]=="reachable":
 result["status"]="success";result["reason_codes"]=["adobe-network-only"];result["disposition"]="CODESPACES_NETWORK_ONLY"
else:
 result["reason_codes"]=["adobe-manual-review"];result["disposition"]="MANUAL_REVIEW"
result["cleanup_complete"]=True
emit(result)
'''


def run_codespaces_diagnostic(
    request: CodespacesDiagnosticRequest,
    *,
    codespace_name: str,
    run: Run = _run,
) -> dict[str, object]:
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
                _ADOBE_REMOTE_RUNNER_SOURCE if request.diagnostic_id == ADOBE_DIAGNOSTIC_ID else _REMOTE_RUNNER_SOURCE,
                str(request.issue_number),
                request.diagnostic_id,
                request.request_id,
                codespace_name,
            ),
            timeout=_RUN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        evidence = _failure(request, "codespaces-diagnostic-transport-timeout", codespace_name)
        stdout_tail, stdout_truncated = _bounded_text(exc.stdout)
        stderr_tail, stderr_truncated = _bounded_text(exc.stderr)
        evidence.update(
            {
                "ssh_exit_code": None,
                "ssh_stdout_tail": stdout_tail,
                "ssh_stdout_truncated": stdout_truncated,
                "ssh_stderr_tail": stderr_tail,
                "ssh_stderr_truncated": stderr_truncated,
                "transport_timeout_seconds": _RUN_TIMEOUT_SECONDS,
            }
        )
        return evidence

    if completed.returncode != 0:
        evidence = _failure(request, "codespaces-diagnostic-ssh-failed", codespace_name)
        stderr_tail, stderr_truncated = _bounded_text(completed.stderr)
        evidence.update(
            {
                "ssh_exit_code": completed.returncode,
                "ssh_stderr_tail": stderr_tail,
                "ssh_stderr_truncated": stderr_truncated,
            }
        )
        return evidence

    framed = _extract_framed_payload(completed.stdout)
    if framed is None:
        return _failure(request, "codespaces-diagnostic-frame-invalid", codespace_name)
    try:
        payload = json.loads(framed)
    except json.JSONDecodeError:
        return _failure(request, "codespaces-diagnostic-evidence-not-json", codespace_name)
    if type(payload) is not dict:
        return _failure(request, "codespaces-diagnostic-evidence-malformed", codespace_name)

    fixed = {
        "repository": request.repository,
        "issue_number": request.issue_number,
        "diagnostic_id": request.diagnostic_id,
        "request_id": request.request_id,
        "codespace_name": codespace_name,
        "codespaces_profile_id": APPROVED_CODESPACE_PROFILE_ID,
        "execution_surface_id": surface_id(codespace_name),
        "workspace_side_effects_performed": False,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }
    if any(payload.get(key) != value for key, value in fixed.items()):
        return _failure(request, "codespaces-diagnostic-evidence-identity-mismatch", codespace_name)
    if payload.get("status") not in {"success", "needs-decision"}:
        return _failure(request, "codespaces-diagnostic-status-invalid", codespace_name)
    if payload.get("cleanup_complete") is not True:
        return _failure(request, "codespaces-diagnostic-cleanup-invalid", codespace_name)
    if request.diagnostic_id == ADOBE_DIAGNOSTIC_ID:
        allowed_dispositions = {
            "CODESPACES_BLOCKED_UNSUPPORTED_PLATFORM",
            "CODESPACES_BLOCKED_GRAPHICS",
            "CODESPACES_ADOBE_MINIMUM_PROBE_PASS",
            "CODESPACES_NETWORK_ONLY",
            "CODESPACES_EXECUTION_PATH_BLOCKED",
            "MANUAL_REVIEW",
        }
        if payload.get("requested_url") != ADOBE_EXPRESS_URL:
            return _failure(request, "codespaces-diagnostic-evidence-identity-mismatch", codespace_name)
        if payload.get("disposition") not in allowed_dispositions:
            return _failure(request, "codespaces-diagnostic-status-invalid", codespace_name)
        serialized = json.dumps(payload, sort_keys=True).lower()
        forbidden_evidence_keys = (
            "\"cookie\"",
            "\"cookies\"",
            "\"token\"",
            "\"password\"",
            "\"authorization\"",
            "\"profile_contents\"",
            "\"raw_html\"",
        )
        if any(key in serialized for key in forbidden_evidence_keys):
            return _failure(request, "codespaces-diagnostic-sensitive-evidence-rejected", codespace_name)
    environment_id = payload.get("environment_health_evidence_id")
    if (
        payload.get("status") == "success"
        and (
            type(environment_id) is not str
            or not environment_id.startswith("sha256:")
        )
    ):
        return _failure(request, "codespaces-environment-health-evidence-invalid", codespace_name)
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

    started_at = _utc_now()
    ingress = _ingress_from_file(args.transport)
    route, request = select_codespaces_diagnostic(ingress)
    args.route_output.parent.mkdir(parents=True, exist_ok=True)
    args.route_output.write_text(
        json.dumps(route, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    if route["handled"] is True:
        assert request is not None
        evidence = (
            run_codespaces_diagnostic(request, codespace_name=str(route["codespace_name"]))
            if route["selected"] is True
            else _failure(
                request,
                str(route["reason_codes"][0]),
                route["codespace_name"] if type(route["codespace_name"]) is str else None,
            )
        )
        evidence = _attach_invocation_metadata(evidence, started_at=started_at)
        args.result_output.write_text(
            json.dumps({"diagnostic": evidence}, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
