"""Bounded deletion-safe retirement inventory for the fixed Agent OS GCE host.

The collector is read-only and emits only whitelisted metadata. It never returns
metadata values, credential contents, browser-profile contents, arbitrary file
contents, cron contents, container names, or repository file names.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from typing import Callable, Sequence

PROJECT = "agent-os-502614"
ZONE = "us-central1-a"
INSTANCE = "agent-os-test"
MAX_ITEMS = 100
UNOBSERVED_EVIDENCE = (
    "external-ip-allocation", "dns-references", "firewall-iap-os-login-bindings",
    "additional-repositories-worktrees", "user-services", "databases",
    "checkpoint-lease-disposition", "generated-asset-retention",
)

Run = Callable[..., subprocess.CompletedProcess[str]]
HostRun = Callable[[str], subprocess.CompletedProcess[str]]

_HOST_FRAME_START = "===AGENT-OS-RETIREMENT-INVENTORY-JSON-BEGIN==="
_HOST_FRAME_END = "===AGENT-OS-RETIREMENT-INVENTORY-JSON-END==="

_HOST_SOURCE = r'''import glob,json,os,pwd,subprocess
home=pwd.getpwuid(os.geteuid()).pw_dir
def exists(p):
 try:return os.path.exists(p)
 except OSError:return False
def count_glob(pattern,limit=101):
 try:
  n=0
  for _ in glob.iglob(pattern):
   n+=1
   if n>=limit:break
  return n
 except Exception:return None
def run(argv,timeout=15):
 try:return subprocess.run(argv,capture_output=True,text=True,check=False,timeout=timeout)
 except Exception:return None
def repo(path):
 if not exists(os.path.join(path,".git")):return {"path":path,"status":"absent"}
 branch=run(["git","-C",path,"rev-parse","--abbrev-ref","HEAD"])
 dirty=run(["git","-C",path,"status","--porcelain=v1"])
 ahead=run(["git","-C",path,"rev-list","--count","@{upstream}..HEAD"])
 return {"path":path,"status":"observed","branch":branch.stdout.strip()[:160] if branch and branch.returncode==0 else None,"dirty_entry_count":len(dirty.stdout.splitlines()) if dirty and dirty.returncode==0 else None,"unpushed_commit_count":int(ahead.stdout.strip()) if ahead and ahead.returncode==0 and ahead.stdout.strip().isdigit() else None}
def backing(path):
 if not exists(path):return {"status":"absent"}
 r=run(["findmnt","-T",path,"-n","-o","SOURCE,TARGET,FSTYPE"])
 if r is None or r.returncode!=0:return {"status":"unknown","reason":"findmnt-unavailable"}
 parts=r.stdout.strip().split(None,2)
 return {"status":"observed","source":parts[0][:200] if len(parts)>0 else None,"target":parts[1][:200] if len(parts)>1 else None,"fstype":parts[2][:80] if len(parts)>2 else None}
browser_rel={".config/google-chrome":"google-chrome",".config/chromium":"chromium",".config/microsoft-edge":"microsoft-edge"}
profiles=[]
for rel,name in browser_rel.items():
 p=os.path.join(home,rel);profiles.append({"kind":name,"path":p,"present":exists(p),"backing_storage":backing(p)})
repos=[repo(p) for p in (os.path.join(home,"agent-os"),os.path.join(home,"workspace","agent-os"),"/opt/agent-os","/srv/agent-os")]
svc=run(["systemctl","--no-pager","--plain","--type=service","--state=running","--no-legend"])
timer=run(["systemctl","--no-pager","--plain","--type=timer","--all","--no-legend"])
docker=run(["docker","volume","ls","-q"])
cron=run(["crontab","-l"])
out={"schema_version":"1.0","status":"observed","reason_codes":["host-retirement-inventory-observed"],"home":home,"browser_profiles":profiles,"repositories":repos,"persistent_state":{"var_lib_agent_os_present":exists("/var/lib/agent-os"),"home_agent_os_state_present":exists(os.path.join(home,".agent-os")),"tmp_agent_os_entry_count":count_glob("/tmp/agent-os-*"),"var_log_agent_os_present":exists("/var/log/agent-os")},"services":{"running_service_count":len(svc.stdout.splitlines()) if svc and svc.returncode==0 else None,"timer_count":len(timer.stdout.splitlines()) if timer and timer.returncode==0 else None,"user_crontab_present":True if cron and cron.returncode==0 else (False if cron and cron.returncode==1 else None)},"containers":{"docker_volume_count":len(docker.stdout.splitlines()) if docker and docker.returncode==0 else None},"credential_presence":{"ssh_directory_present":exists(os.path.join(home,".ssh")),"gcloud_adc_present":exists(os.path.join(home,".config","gcloud","application_default_credentials.json"))},"credential_contents_emitted":False,"profile_contents_emitted":False,"repository_file_names_emitted":False,"side_effects_performed":False}
''' + (
    f"print({_HOST_FRAME_START!r})\n"
    'print(json.dumps(out, sort_keys=True, separators=(",", ":")))\n'
    f"print({_HOST_FRAME_END!r})\n"
)

HOST_RETIREMENT_INVENTORY_COMMAND = "/usr/bin/python3 -c " + shlex.quote(_HOST_SOURCE)


def _run_json(run: Run, argv: Sequence[str], reason: str) -> object:
    result = run(tuple(argv), timeout=60)
    if result.returncode != 0:
        raise ValueError(reason)
    try:
        return json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(reason) from exc


def _bounded_list(value: object, reason: str) -> list[dict[str, object]]:
    if type(value) is not list or len(value) > MAX_ITEMS:
        raise ValueError(reason)
    if any(type(item) is not dict for item in value):
        raise ValueError(reason)
    return value


def _name_from_url(value: object) -> str | None:
    if type(value) is not str:
        return None
    return value.rsplit("/", 1)[-1][:160]


def _cloud_inventory(run: Run) -> tuple[dict[str, object], list[str]]:
    instance = _run_json(
        run,
        (
            "gcloud", "compute", "instances", "describe", INSTANCE,
            "--project", PROJECT, "--zone", ZONE, "--format=json",
        ),
        "retirement-instance-read-failed",
    )
    if type(instance) is not dict:
        raise ValueError("retirement-instance-malformed")

    reasons: list[str] = []
    disks = []
    for item in _bounded_list(instance.get("disks", []), "retirement-disks-malformed"):
        if type(item.get("autoDelete")) is not bool:
            reasons.append("retirement-disk-autodelete-unobserved")
        if type(item.get("source")) is not str or not item.get("source").startswith(f"projects/{PROJECT}/zones/{ZONE}/disks/"):
            reasons.append("retirement-disk-identity-unobserved")
        disks.append({
            "source": _name_from_url(item.get("source")),
            "source_resource": item.get("source") if type(item.get("source")) is str and item.get("source").startswith(f"projects/{PROJECT}/zones/{ZONE}/disks/") else "UNKNOWN",
            "boot": item.get("boot") is True,
            "auto_delete": item.get("autoDelete") if type(item.get("autoDelete")) is bool else "UNKNOWN",
            "mode": item.get("mode") if type(item.get("mode")) is str else None,
        })

    networks = []
    for item in _bounded_list(instance.get("networkInterfaces", []), "retirement-network-malformed"):
        configs = item.get("accessConfigs", [])
        if type(configs) is not list or len(configs) > 20:
            raise ValueError("retirement-network-malformed")
        networks.append({
            "network": _name_from_url(item.get("network")),
            "subnetwork": _name_from_url(item.get("subnetwork")),
            "internal_ip": item.get("networkIP") if type(item.get("networkIP")) is str else None,
            "external_ips": [
                cfg.get("natIP") for cfg in configs
                if type(cfg) is dict and type(cfg.get("natIP")) is str
            ],
        })

    metadata = instance.get("metadata", {})
    metadata_items = metadata.get("items", []) if type(metadata) is dict else []
    if type(metadata_items) is not list or len(metadata_items) > MAX_ITEMS:
        raise ValueError("retirement-metadata-malformed")
    keys = sorted(
        item["key"][:160] for item in metadata_items
        if type(item) is dict and type(item.get("key")) is str
    )
    if len(keys) != len(metadata_items):
        raise ValueError("retirement-metadata-malformed")

    snapshots: list[dict[str, object]] | str = "UNKNOWN"
    images: list[dict[str, object]] | str = "UNKNOWN"
    for kind, argv, failure in (
        ("snapshots", ("gcloud", "compute", "snapshots", "list", "--project", PROJECT, "--format=json(name,sourceDisk,status)"), "retirement-snapshot-read-failed"),
        ("images", ("gcloud", "compute", "images", "list", "--project", PROJECT, "--no-standard-images", "--format=json(name,sourceDisk,status)"), "retirement-image-read-failed"),
    ):
        try:
            raw = _run_json(run, argv, failure)
            entries = _bounded_list(raw, "retirement-" + kind + "-malformed")
            values = [{"name": item.get("name"), "source_disk": _name_from_url(item.get("sourceDisk")), "status": item.get("status")} for item in entries if type(item.get("name")) is str]
            if len(values) != len(entries):
                raise ValueError("retirement-" + kind + "-malformed")
            if kind == "snapshots":
                snapshots = values
            else:
                images = values
        except ValueError as exc:
            reasons.append(str(exc))

    return {
        "status": instance.get("status") if type(instance.get("status")) is str else "UNKNOWN",
        "machine_type": _name_from_url(instance.get("machineType")),
        "disks": disks,
        "networks": networks,
        "metadata_keys": keys,
        "startup_script_present": "startup-script" in keys or "startup-script-url" in keys,
        "snapshots": snapshots,
        "images": images,
        "metadata_values_emitted": False,
    }, reasons


def _extract_host_payload(stdout: str) -> dict[str, object]:
    if type(stdout) is not str:
        raise ValueError("host-retirement-inventory-malformed")
    if stdout.count(_HOST_FRAME_START) != 1 or stdout.count(_HOST_FRAME_END) != 1:
        raise ValueError("host-retirement-inventory-frame-invalid")
    start = stdout.find(_HOST_FRAME_START) + len(_HOST_FRAME_START)
    end = stdout.find(_HOST_FRAME_END)
    if end <= start:
        raise ValueError("host-retirement-inventory-frame-invalid")
    try:
        payload = json.loads(stdout[start:end].strip())
    except json.JSONDecodeError as exc:
        raise ValueError("host-retirement-inventory-json-invalid") from exc
    if type(payload) is not dict:
        raise ValueError("host-retirement-inventory-malformed")
    if payload.get("credential_contents_emitted") is not False or payload.get("profile_contents_emitted") is not False or payload.get("repository_file_names_emitted") is not False or payload.get("side_effects_performed") is not False:
        raise ValueError("host-retirement-inventory-contract-violation")
    return payload


def collect_retirement_inventory(run: Run, host_run: HostRun | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": "1.0",
        "status": "needs-decision",
        "reason_codes": ["retirement-inventory-unavailable"],
        "project": PROJECT,
        "zone": ZONE,
        "instance": INSTANCE,
        "cloud": {"status": "unknown"},
        "host": {"status": "unknown"},
        "credential_contents_emitted": False,
        "profile_contents_emitted": False,
        "external_write_performed": False,
        "side_effects_performed": False,
    }
    # A successful bounded read is not proof that the VM can be retired.
    # Preserve every deletion-critical gap explicitly for the #3099 consumer.
    result["unobserved_evidence"] = {
        key: "UNKNOWN" for key in UNOBSERVED_EVIDENCE
    }
    reasons = [f"retirement-{key}-unobserved" for key in UNOBSERVED_EVIDENCE]
    try:
        cloud, cloud_reasons = _cloud_inventory(run)
        result["cloud"] = cloud
        reasons.extend(cloud_reasons)
    except ValueError as exc:
        reasons.append(str(exc)[:160])
    if host_run is None:
        reasons.append("retirement-host-unavailable")
        result["reason_codes"] = reasons
        return result
    try:
        host = host_run(HOST_RETIREMENT_INVENTORY_COMMAND)
        if host.returncode != 0:
            raise ValueError("host-retirement-inventory-command-failed")
        result["host"] = _extract_host_payload(host.stdout)
        payload = result["host"]
        for section in ("services", "containers", "persistent_state"):
            values = payload.get(section, {})
            if type(values) is not dict or not values or None in values.values():
                reasons.append(f"retirement-host-{section}-unobserved")
        for profile in payload.get("browser_profiles", []):
            if profile.get("present") is True and profile.get("backing_storage", {}).get("status") != "observed":
                reasons.append("retirement-browser-storage-unobserved")
                break
        for repository in payload.get("repositories", []):
            if repository.get("status") == "observed" and any(
                repository.get(key) is None
                for key in ("branch", "dirty_entry_count", "unpushed_commit_count")
            ):
                reasons.append("retirement-repository-state-unobserved")
                break
    except ValueError as exc:
        reasons.append(str(exc)[:160])
    if reasons:
        result["reason_codes"] = reasons
        return result
    result["status"] = "observed"
    result["reason_codes"] = ["retirement-inventory-observed"]
    return result


__all__ = [
    "HOST_RETIREMENT_INVENTORY_COMMAND",
    "INSTANCE",
    "MAX_ITEMS",
    "PROJECT",
    "ZONE",
    "collect_retirement_inventory",
]
