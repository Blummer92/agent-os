from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "08_Tooling/agent-os-execution-service/scripts"
SESSION = SCRIPTS / "agent-os-schoology-browser-session"
INSTALLER = SCRIPTS / "install-schoology-browser-bootstrap"
OTHER_SESSIONS = (
    SCRIPTS / "agent-os-adobe-browser-session",
    SCRIPTS / "agent-os-tinkercad-browser-session",
    SCRIPTS / "agent-os-canva-browser-session",
)

def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def test_bootstrap_sources_are_executable_in_clean_checkout() -> None:
    assert SESSION.stat().st_mode & 0o111
    assert INSTALLER.stat().st_mode & 0o111

def test_fixed_schoology_target_identity_and_ports_are_not_selectable() -> None:
    session = _text(SESSION)
    installer = _text(INSTALLER)
    assert '[ "$#" -eq 0 ] || fail "arguments are not supported"' in session
    assert '[ "$#" -eq 0 ] || fail "arguments are not supported"' in installer
    assert "schoology-default" in session
    assert "CAPTURE_USER=agent-os-schoology-capture" in session
    assert "CAPTURE_HOME=/var/lib/agent-os/schoology-capture-home" in session
    assert "PROFILE_DIR=$CAPTURE_HOME/.agent-os/browser-profiles/schoology-kami" in session
    assert "DISPLAY_ID=:100" in session
    assert "VNC_PORT=5904" in session
    assert "NOVNC_PORT=6083" in session
    assert "START_URL=https://dpscd.schoology.com/home" in session
    assert "SESSION_TTL_SECONDS=1800" in session

def test_schoology_profile_and_runtime_are_isolated_from_existing_products() -> None:
    session = _text(SESSION)
    for other_path in OTHER_SESSIONS:
        other = _text(other_path)
        assert "agent-os-schoology-capture" not in other
        assert "schoology-capture-home" not in other
        assert "browser-profiles/schoology-kami" not in other
        assert "DISPLAY_ID=:100" not in other
        assert "NOVNC_PORT=6083" not in other
    assert "-localhost" in session
    assert '"127.0.0.1:$NOVNC_PORT"' in session
    assert '"127.0.0.1:$VNC_PORT"' in session

def test_schoology_exposes_no_remote_debugging_or_web_auth_material() -> None:
    combined = (_text(SESSION) + "\n" + _text(INSTALLER)).lower()
    for forbidden in (
        "--remote-debugging-port", "--remote-debugging-address", "--remote-debugging-pipe",
        "devtoolsactiveport", "socat", "--url", "--profile", "provider_selector",
        "password=", "token=", "mfa=", "credential=",
        "document.cookie", "set-cookie", "cookie_header", "cookies.json", "--cookie",
    ):
        assert forbidden not in combined

def test_lifecycle_evidence_never_asserts_auth_ready() -> None:
    session = _text(SESSION)
    evidence = "\n".join(line for line in session.splitlines() if "schema_name" in line and "printf" in line)
    assert "agent-os-schoology-browser-bootstrap-session" in evidence
    assert "schoology-default" in evidence
    assert "auth_ready_asserted\\\":false" in evidence
    assert "profile_material_emitted\\\":false" in evidence
    assert "capture_invoked\\\":false" in evidence
    assert "scheduler_invoked\\\":false" in evidence
    assert "external_write_authorized\\\":false" in evidence
    assert "live_activation_authorized\\\":false" in evidence
    assert "AUTH_READY" not in evidence
    assert "/var/lib/agent-os" not in evidence

def test_bootstrap_does_not_invoke_capture_or_replay() -> None:
    combined = (_text(SESSION) + "\n" + _text(INSTALLER)).lower()
    for forbidden in ("@puppeteer/replay", "puppeteer", "recording.json", "software-tutorial-capture-v1", "workflow_scheduler"):
        assert forbidden not in combined
