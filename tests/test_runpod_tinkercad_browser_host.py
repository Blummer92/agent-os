from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).parents[1]
SESSION=ROOT/"08_Tooling/agent-os-execution-service/scripts/agent-os-runpod-tinkercad-browser-session"
CONTRACT=ROOT/"08_Tooling/agent-os-execution-service/runpod/tinkercad-runtime-contract.json"
RUNBOOK=ROOT/"08_Tooling/agent-os-execution-service/docs/RUNPOD_TINKERCAD_BROWSER_HOST.md"

def text(path:Path)->str:return path.read_text(encoding="utf-8")

def test_fixed_provider_gpu_and_two_hour_bound():
    contract=json.loads(text(CONTRACT)); session=text(SESSION)
    assert contract["provider"]=="runpod"
    assert contract["cloud_type"]=="COMMUNITY"
    assert contract["gpu"]=="NVIDIA RTX A5000"
    assert contract["lifecycle"]["max_seconds"]==7200
    assert "SESSION_TTL_SECONDS=7200" in session
    assert '[ "$#" -eq 0 ] || fail "arguments are not supported"' in session

def test_gpu_backed_display_is_required_and_old_software_path_is_not_recreated():
    session=text(SESSION); runbook=text(RUNBOOK)
    assert 'NVIDIA_SMI=/usr/bin/nvidia-smi' in session
    assert '[ "$DISPLAY" = "$DISPLAY_ID" ] || fail "unexpected display identity"' in session
    assert "gpu-lost" in session
    assert "GPU-backed Xorg/X11" in runbook
    assert "llvmpipe" in runbook
    assert "Xvfb" not in session

def test_viewer_is_loopback_only_and_ssh_tunneled():
    session=text(SESSION); contract=json.loads(text(CONTRACT)); runbook=text(RUNBOOK)
    assert "-localhost" in session
    assert '"127.0.0.1:$NOVNC_PORT"' in session
    assert '"127.0.0.1:$VNC_PORT"' in session
    assert contract["viewer"]["transport"]=="SSH local forwarding only"
    assert "exposes no public viewer" in runbook

def test_security_bypasses_and_remote_debugging_are_absent():
    combined=text(SESSION)+"\n"+text(RUNBOOK)
    for forbidden in ("--enable-unsafe-swiftshader","--ignore-gpu-blocklist","--disable-gpu-sandbox","--disable-web-security","--remote-debugging-port","--remote-debugging-pipe","DevToolsActivePort"):
        assert forbidden not in text(SESSION)
    assert "No CDP or remote-debugging port is permitted" in combined

def test_profile_is_ephemeral_and_never_persisted():
    session=text(SESSION); contract=json.loads(text(CONTRACT))
    assert 'rm -rf "$PROFILE_ROOT"' in session
    assert contract["authentication"]["profile"]=="ephemeral-per-pod"
    assert contract["authentication"]["persistent_storage_allowed"] is False
    assert set(contract["persistent_storage"]["forbidden"])=={"cookies","tokens","browser profile","authentication state"}
    assert '"profile_persisted":false' in session.replace("\\\"","\"")

def test_repository_contract_performs_no_live_provider_action():
    combined=text(SESSION)+"\n"+text(CONTRACT)+"\n"+text(RUNBOOK)
    assert '"live_provider_mutation_authorized": false' in text(CONTRACT)
    for forbidden in ("runpodctl","runpod create","api.runpod.io","RUNPOD_API_KEY"):
        assert forbidden not in combined
    assert "#2788 remains blocked" in text(RUNBOOK)
