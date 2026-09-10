"""Finite read-only sudo admission evidence for the governed GCE runtime inspector."""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import Callable

HELPER = "/usr/local/libexec/agent-os-host-install"
WORKFLOW = Path(__file__).resolve().parents[5] / ".github/workflows/agent-os-governed-invocation.yml"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_PIN = re.compile(r"^\s*HOST_RUNTIME_SOURCE_SHA:\s*([0-9a-f]{40})\s*$", re.MULTILINE)
_FRAME_START = "===AGENT-OS-SUDO-INSPECTION-JSON-BEGIN==="
_FRAME_END = "===AGENT-OS-SUDO-INSPECTION-JSON-END==="
_MAX_FRAME_CHARS = 8192
_MAX_POLICY_LINE_COUNT = 256
_MAX_PRINCIPAL_CHARS = 128
_TRUSTED_PATHS = ("/", "/usr", "/usr/local", "/usr/local/libexec")
_DISPOSITIONS = {
    "current-sha-rule",
    "old-sha-rule",
    "missing-rule",
    "wrong-principal",
    "helper-bootstrap-drift",
    "other-bounded-sudo-defect",
    "unexpected-broad-privilege",
}


def expected_runtime_source_sha(path: Path = WORKFLOW) -> str:
    values = _PIN.findall(path.read_text(encoding="utf-8"))
    if len(values) != 1:
        raise ValueError("runtime-source-sha-unavailable")
    return values[0]


def alternate_sha(expected_sha: str) -> str:
    if _SHA.fullmatch(expected_sha) is None:
        raise ValueError("runtime-source-sha-invalid")
    return ("0" if expected_sha[0] != "0" else "1") + expected_sha[1:]


def _remote_source(expected_sha: str) -> str:
    alternate = alternate_sha(expected_sha)
    return f'''import json,os,pwd,re,stat,subprocess\nhelper={HELPER!r}\nexpected={expected_sha!r}\nalternate={alternate!r}\ndef meta(path):\n try:\n  st=os.lstat(path);return {{"path":path,"exists":True,"symlink":stat.S_ISLNK(st.st_mode),"uid":st.st_uid,"gid":st.st_gid,"mode":format(st.st_mode & 0o7777,"04o")}}\n except FileNotFoundError:return {{"path":path,"exists":False}}\n except Exception:return {{"path":path,"exists":False}}\ndef trusted(item):\n return item.get("exists") is True and item.get("symlink") is False and item.get("uid")==0 and item.get("gid")==0 and int(item.get("mode","7777"),8)&0o022==0\ndef probe(sha):\n p=subprocess.run(["/usr/bin/sudo","-n","-l",helper,"--source-sha",sha],capture_output=True,text=True,check=False)\n return {{"admitted":p.returncode==0,"exit_code":p.returncode}}\nlisting=subprocess.run(["/usr/bin/sudo","-n","-l"],capture_output=True,text=True,check=False)\ntext=(listing.stdout+"\\n"+listing.stderr)[:16384]\nlines=[line.strip() for line in text.splitlines() if helper in line or "NOPASSWD: ALL" in line or re.search(r"/(?:bin|sbin)/(?:sh|bash|dash|zsh|python(?:3(?:\\.\\d+)?)?)\\b",line)]\nhelper_lines=[line for line in lines if helper in line]\nsha_values=[]\nfor line in helper_lines:\n sha_values.extend(re.findall(r"--source-sha\\s+([0-9a-f]{{40}})",line))\nsha_values=sorted(set(sha_values))\nbroad=any("NOPASSWD: ALL" in line or "*" in line or "?" in line or "[" in line or re.search(r"/(?:bin|sbin)/(?:sh|bash|dash|zsh|python(?:3(?:\\.\\d+)?)?)\\b",line) for line in lines) or len(sha_values)>1\ncurrent=probe(expected);other=probe(alternate)\nhelper_meta=meta(helper);ancestors=[meta(path) for path in {list(_TRUSTED_PATHS)!r}]\nbootstrap_drift=not trusted(helper_meta) or any(not trusted(item) for item in ancestors)\nwrong_principal=listing.returncode!=0 and re.search(r"not allowed to run sudo|may not run sudo|not in the sudoers",text,re.I) is not None\nif broad or other["admitted"]: disposition="unexpected-broad-privilege"\nelif bootstrap_drift: disposition="helper-bootstrap-drift"\nelif wrong_principal: disposition="wrong-principal"\nelif current["admitted"] and sha_values in ([],[expected]): disposition="current-sha-rule"\nelif len(sha_values)==1 and sha_values[0]!=expected: disposition="old-sha-rule"\nelif not helper_lines and not current["admitted"]: disposition="missing-rule"\nelse: disposition="other-bounded-sudo-defect"\ntry: principal=pwd.getpwuid(os.geteuid()).pw_name\nexcept Exception: principal=str(os.geteuid())\nout={{"status":"observed","disposition":disposition,"expected_source_sha":expected,"authorized_source_sha":sha_values[0] if len(sha_values)==1 else None,"authorized_source_sha_count":len(sha_values),"exact_command_admitted":current["admitted"],"alternate_command_admitted":other["admitted"],"broad_privilege_detected":broad or other["admitted"],"effective_principal":principal[:128],"helper":helper_meta,"trusted_ancestors":ancestors,"policy_line_count":len(lines),"execution_authorized":False,"scheduler_invoked":False,"discovery_invoked":False,"resume_invoked":False,"side_effects_performed":False}}\nprint({_FRAME_START!r});print(json.dumps(out,sort_keys=True,separators=(",",":")));print({_FRAME_END!r})'''


def command(expected_sha: str) -> str:
    return f"/usr/bin/python3 -c {shlex.quote(_remote_source(expected_sha))}"


def unavailable_sudo_admission(reason: str, expected_sha: str | None = None) -> dict[str, object]:
    return {
        "status": "needs-decision",
        "disposition": "inspection-unavailable",
        "reason_codes": [reason],
        "expected_source_sha": expected_sha,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "discovery_invoked": False,
        "resume_invoked": False,
        "side_effects_performed": False,
    }


def _project_meta(value: object, expected_path: str) -> dict[str, object]:
    if type(value) is not dict or value.get("path") != expected_path or type(value.get("exists")) is not bool:
        raise ValueError("sudo-inspection-contract-violation")
    projected: dict[str, object] = {"path": expected_path, "exists": value["exists"]}
    if value["exists"] is False:
        return projected
    symlink = value.get("symlink")
    uid = value.get("uid")
    gid = value.get("gid")
    mode = value.get("mode")
    if type(symlink) is not bool or type(uid) is not int or type(gid) is not int:
        raise ValueError("sudo-inspection-contract-violation")
    if type(mode) is not str or re.fullmatch(r"[0-7]{4}", mode) is None:
        raise ValueError("sudo-inspection-contract-violation")
    projected.update({"symlink": symlink, "uid": uid, "gid": gid, "mode": mode})
    return projected


def _project_payload(payload: object, expected_sha: str) -> dict[str, object]:
    if type(payload) is not dict or payload.get("status") != "observed":
        raise ValueError("sudo-inspection-contract-violation")
    if payload.get("expected_source_sha") != expected_sha:
        raise ValueError("sudo-inspection-contract-violation")
    disposition = payload.get("disposition")
    if disposition not in _DISPOSITIONS:
        raise ValueError("sudo-inspection-contract-violation")
    principal = payload.get("effective_principal")
    if type(principal) is not str or not principal or len(principal) > _MAX_PRINCIPAL_CHARS:
        raise ValueError("sudo-inspection-contract-violation")
    authorized_sha = payload.get("authorized_source_sha")
    if authorized_sha is not None and (type(authorized_sha) is not str or _SHA.fullmatch(authorized_sha) is None):
        raise ValueError("sudo-inspection-contract-violation")
    authorized_count = payload.get("authorized_source_sha_count")
    policy_line_count = payload.get("policy_line_count")
    if type(authorized_count) is not int or not 0 <= authorized_count <= 16:
        raise ValueError("sudo-inspection-contract-violation")
    if type(policy_line_count) is not int or not 0 <= policy_line_count <= _MAX_POLICY_LINE_COUNT:
        raise ValueError("sudo-inspection-contract-violation")
    if (authorized_count == 1) != (authorized_sha is not None):
        raise ValueError("sudo-inspection-contract-violation")
    exact = payload.get("exact_command_admitted")
    alternate = payload.get("alternate_command_admitted")
    broad = payload.get("broad_privilege_detected")
    if type(exact) is not bool or type(alternate) is not bool or type(broad) is not bool:
        raise ValueError("sudo-inspection-contract-violation")
    if alternate and not broad:
        raise ValueError("sudo-inspection-contract-violation")
    for flag in ("execution_authorized", "scheduler_invoked", "discovery_invoked", "resume_invoked", "side_effects_performed"):
        if payload.get(flag) is not False:
            raise ValueError("sudo-inspection-contract-violation")
    helper = _project_meta(payload.get("helper"), HELPER)
    ancestors_raw = payload.get("trusted_ancestors")
    if type(ancestors_raw) is not list or len(ancestors_raw) != len(_TRUSTED_PATHS):
        raise ValueError("sudo-inspection-contract-violation")
    ancestors = [_project_meta(item, path) for item, path in zip(ancestors_raw, _TRUSTED_PATHS)]
    if disposition == "current-sha-rule" and (not exact or alternate or broad or authorized_sha not in (None, expected_sha)):
        raise ValueError("sudo-inspection-contract-violation")
    if disposition == "old-sha-rule" and (exact or broad or authorized_sha in (None, expected_sha)):
        raise ValueError("sudo-inspection-contract-violation")
    if disposition == "missing-rule" and (exact or authorized_count != 0):
        raise ValueError("sudo-inspection-contract-violation")
    if disposition == "unexpected-broad-privilege" and not broad:
        raise ValueError("sudo-inspection-contract-violation")
    return {
        "status": "observed",
        "disposition": disposition,
        "expected_source_sha": expected_sha,
        "authorized_source_sha": authorized_sha,
        "authorized_source_sha_count": authorized_count,
        "exact_command_admitted": exact,
        "alternate_command_admitted": alternate,
        "broad_privilege_detected": broad,
        "effective_principal": principal,
        "helper": helper,
        "trusted_ancestors": ancestors,
        "policy_line_count": policy_line_count,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "discovery_invoked": False,
        "resume_invoked": False,
        "side_effects_performed": False,
    }


def collect_sudo_admission(
    run_ssh: Callable[[str], subprocess.CompletedProcess[str]], expected_sha: str
) -> dict[str, object]:
    if _SHA.fullmatch(expected_sha) is None:
        return unavailable_sudo_admission("runtime-source-sha-invalid", expected_sha)
    result = run_ssh(command(expected_sha))
    if result.returncode != 0:
        return unavailable_sudo_admission("sudo-inspection-command-failed", expected_sha)
    stdout = result.stdout if type(result.stdout) is str else ""
    if stdout.count(_FRAME_START) != 1 or stdout.count(_FRAME_END) != 1:
        return unavailable_sudo_admission("sudo-inspection-frame-invalid", expected_sha)
    start = stdout.find(_FRAME_START)
    end = stdout.find(_FRAME_END)
    if end <= start:
        return unavailable_sudo_admission("sudo-inspection-frame-invalid", expected_sha)
    raw = stdout[start + len(_FRAME_START) : end].strip()
    if len(raw) > _MAX_FRAME_CHARS:
        return unavailable_sudo_admission("sudo-inspection-frame-too-large", expected_sha)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return unavailable_sudo_admission("sudo-inspection-evidence-not-json", expected_sha)
    try:
        return _project_payload(payload, expected_sha)
    except ValueError:
        return unavailable_sudo_admission("sudo-inspection-contract-violation", expected_sha)


__all__ = [
    "HELPER",
    "WORKFLOW",
    "alternate_sha",
    "collect_sudo_admission",
    "command",
    "expected_runtime_source_sha",
    "unavailable_sudo_admission",
]
