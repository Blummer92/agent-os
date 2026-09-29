from pathlib import Path

ROOT = Path(__file__).parents[1]
SESSION = ROOT / "08_Tooling/agent-os-execution-service/scripts/agent-os-runpod-tinkercad-browser-session"
RUNBOOK = ROOT / "08_Tooling/agent-os-execution-service/docs/RUNPOD_TINKERCAD_BROWSER_HOST.md"

def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def test_fixed_contract():
    session = text(SESSION)
    assert "CLOUD_TYPE=COMMUNITY" in session
    assert 'GPU_TYPE="NVIDIA RTX A5000"' in session
    assert "SESSION_TTL_SECONDS=7200" in session
    assert '[ "$#" -eq 0 ]' in session

def test_gpu_display_and_security():
    session = text(SESSION)
    assert "nvidia-smi -L" in session and "Xorg " in session and "Xvfb" not in session
    for forbidden in ("--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--disable-gpu-sandbox", "--disable-web-security", "--remote-debugging-port", "--remote-debugging-pipe"):
        assert forbidden not in session

def test_loopback_ephemeral_cleanup():
    session = text(SESSION)
    assert "-localhost" in session
    assert '"127.0.0.1:$NOVNC_PORT"' in session
    assert "mktemp -d /tmp/agent-os-tinkercad-profile." in session
    assert 'rm -rf "$PROFILE_DIR" "$RUNTIME_DIR"' in session

def test_no_live_provider_action():
    combined = text(SESSION) + "\n" + text(RUNBOOK)
    for forbidden in ("runpodctl", "api.runpod.io", "RUNPOD_API_KEY", "pod create", "network volume create"):
        assert forbidden not in combined
    assert "#2788" in text(RUNBOOK)
