"""Finite read-only sudo admission evidence for the governed GCE runtime inspector."""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import Callable

HELPER = "/usr/local/libexec/agent-os-host-install"
WORKFLOW = Path(".github/workflows/agent-os-governed-invocation.yml")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_PIN = re.compile(r"^\s*HOST_RUNTIME_SOURCE_SHA:\s*([0-9a-f]{40})\s*$", re.MULTILINE)
_FRAME_START = "===AGENT-OS-SUDO-INSPECTION-JSON-BEGIN==="
_FRAME_END = "===AGENT-OS-SUDO-INSPECTION-JSON-END==="


def expected_runtime_source_sha(path: Path = WORKFLOW) -> str:
    text = path.read_text(encoding="utf-8")
    values = tuple(dict.fromkeys(_PIN.findall(text)))
    if len(values) != 1:
        raise ValueError("runtime-source-sha-unavailable")
    return values[0]


def alternate_sha(expected_sha: str) -> str:
    if _SHA.fullmatch(expected_sha) is None:
        raise ValueError("runtime-source-sha-invalid")
    return ("0" if expected_sha[0] != "0" else "1") + expected_sha[1:]


def _remote_source(expected_sha: str) -> str:
    alternate = alternate_sha(expected_sha)
    return f'''import json,os,re,subprocess\nhelper={HELPER!r}\nexpected={expected_sha!r}\nalternate={alternate!r}\ndef meta(path):\n try:\n  st=os.lstat(path);return {{"path":path,"exists":True,"symlink":os.path.islink(path),"uid":st.st_uid,"gid":st.st_gid,"mode":format(st.st_mode & 0o7777,"04o")}}\n except FileNotFoundError:return {{"path":path,"exists":False}}\n except Exception as exc:return {{"path":path,"error_class":type(exc).__name__}}\ndef probe(sha):\n p=subprocess.run(["/usr/bin/sudo","-n","-l",helper,"--source-sha",sha],capture_output=True,text=True,check=False)\n return {{"admitted":p.returncode==0,"exit_code":p.returncode}}\nlisting=subprocess.run(["/usr/bin/sudo","-n","-l"],capture_output=True,text=True,check=False)\ntext=(listing.stdout+"\\n"+listing.stderr)[:16384]\nlines=[line.strip() for line in text.splitlines() if helper in line or "NOPASSWD: ALL" in line or re.search(r"/(?:bin|sbin)/(?:sh|bash|dash|zsh|python(?:3(?:\\.\\d+)?)?)\\b",line)]\nhelper_lines=[line for line in lines if helper in line]\nsha_values=[]\nfor line in helper_lines:\n sha_values.extend(re.findall(r"--source-sha\\s+([0-9a-f]{{40}})",line))\nsha_values=sorted(set(sha_values))\nbroad=any("NOPASSWD: ALL" in line or "*" in line or "?" in line or "[" in line or re.search(r"/(?:bin|sbin)/(?:sh|bash|dash|zsh|python(?:3(?:\\.\\d+)?)?)\\b",line) for line in lines) or len(sha_values)>1\ncurrent=probe(expected);other=probe(alternate)\nif broad or other["admitted"]: disposition="unexpected-broad-privilege"\nelif current["admitted"] and sha_values in ([],[expected]): disposition="current-sha-rule"\nelif len(sha_values)==1 and sha_values[0]!=expected: disposition="old-sha-rule"\nelif not helper_lines and not current["admitted"]: disposition="missing-rule"\nelse: disposition="other-bounded-sudo-defect"\nout={{"status":"observed","disposition":disposition,"expected_source_sha":expected,"authorized_source_sha":sha_values[0] if len(sha_values)==1 else None,"authorized_source_sha_count":len(sha_values),"exact_command_admitted":current["admitted"],"alternate_command_admitted":other["admitted"],"broad_privilege_detected":broad or other["admitted"],"helper":meta(helper),"trusted_ancestors":[meta("/"),meta("/usr"),meta("/usr/local"),meta("/usr/local/libexec")],"policy_line_count":len(lines),"execution_authorized":False,"side_effects_performed":False}}\nprint({_FRAME_START!r});print(json.dumps(out,sort_keys=True,separators=(",",":")));print({_FRAME_END!r})'''


def command(expected_sha: str) -> str:
    return f"/usr/bin/python3 -c {shlex.quote(_remote_source(expected_sha))}"


def collect_sudo_admission(run_ssh: Callable[[str], subprocess.CompletedProcess[str]], expected_sha: str) -> dict[str, object]:
    base = {"status":"needs-decision","disposition":"inspection-unavailable","expected_source_sha":expected_sha,"execution_authorized":False,"side_effects_performed":False}
    if _SHA.fullmatch(expected_sha) is None:
        return base | {"reason_codes":["runtime-source-sha-invalid"]}
    result = run_ssh(command(expected_sha))
    if result.returncode != 0:
        return base | {"reason_codes":["sudo-inspection-command-failed"]}
    start = result.stdout.count(_FRAME_START); end = result.stdout.count(_FRAME_END)
    if start != 1 or end != 1 or result.stdout.find(_FRAME_END) <= result.stdout.find(_FRAME_START):
        return base | {"reason_codes":["sudo-inspection-frame-invalid"]}
    raw = result.stdout.split(_FRAME_START,1)[1].split(_FRAME_END,1)[0].strip()
    try: payload = json.loads(raw)
    except json.JSONDecodeError: return base | {"reason_codes":["sudo-inspection-evidence-not-json"]}
    if type(payload) is not dict or payload.get("expected_source_sha") != expected_sha or payload.get("execution_authorized") is not False or payload.get("side_effects_performed") is not False:
        return base | {"reason_codes":["sudo-inspection-contract-violation"]}
    return payload

__all__ = ["HELPER","WORKFLOW","alternate_sha","collect_sudo_admission","command","expected_runtime_source_sha"]
