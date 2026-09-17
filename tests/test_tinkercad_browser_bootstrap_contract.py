from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
SESSION = ROOT / "08_Tooling/agent-os-execution-service/scripts/agent-os-tinkercad-browser-session"
INSTALLER = ROOT / "08_Tooling/agent-os-execution-service/scripts/install-tinkercad-browser-bootstrap"
RUNBOOK = ROOT / "08_Tooling/agent-os-execution-service/docs/TINKERCAD_BROWSER_BOOTSTRAP.md"
ADOBE_SESSION = ROOT / "08_Tooling/agent-os-execution-service/scripts/agent-os-adobe-browser-session"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_bootstrap_sources_are_executable_in_clean_checkout() -> None:
    assert SESSION.stat().st_mode & 0o111
    assert INSTALLER.stat().st_mode & 0o111


def test_fixed_tinkercad_target_and_identity_are_not_selectable() -> None:
    session = _text(SESSION); installer = _text(INSTALLER); normalized_session = session.replace('\\"', '"')
    assert '[ "$#" -eq 0 ] || fail "arguments are not supported"' in session
    assert '[ "$#" -eq 0 ] || fail "arguments are not supported"' in installer
    assert '"browser_session_ref":"tinkercad-default"' in normalized_session
    assert "START_URL=https://www.tinkercad.com/3d-design/" in session
    for forbidden in ("${1", "${2", "getopts", "read -r", "eval "):
        assert forbidden not in session


def test_tinkercad_profile_identity_display_and_ports_are_isolated_from_adobe() -> None:
    session = _text(SESSION); adobe = _text(ADOBE_SESSION)
    assert "CAPTURE_USER=agent-os-tinkercad-capture" in session
    assert "CAPTURE_HOME=/var/lib/agent-os/tinkercad-capture-home" in session
    assert "PROFILE_DIR=$CAPTURE_HOME/.agent-os/browser-profiles/tinkercad" in session
    assert "DISPLAY_ID=:98" in session
    assert "VNC_PORT=5902" in session
    assert "NOVNC_PORT=6081" in session
    assert "SESSION_TTL_SECONDS=1800" in session
    assert "agent-os-tinkercad-capture" not in adobe
    assert "tinkercad-capture-home" not in adobe
    assert "browser-profiles/tinkercad" not in adobe


def test_viewer_is_loopback_only_and_hardened_x11vnc_flags_match_qualified_runtime() -> None:
    session = _text(SESSION)
    assert "-localhost" in session
    assert '"127.0.0.1:$NOVNC_PORT"' in session
    assert '"127.0.0.1:$VNC_PORT"' in session
    for required in ("-nosel", "-noclipboard", "-nosetclipboard", "-notightfilexfer"):
        assert required in session
    assert "-noutrafilexfer" not in session


def test_tinkercad_exposes_no_remote_debugging_or_generic_browser_selector() -> None:
    combined = _text(SESSION) + "\n" + _text(INSTALLER)
    for forbidden in ("--remote-debugging-port", "--remote-debugging-address", "--remote-debugging-pipe", "DevToolsActivePort", "socat", "--url", "--profile", "provider_selector"):
        assert forbidden not in combined


def test_webgl_investigation_does_not_weaken_chromium_security() -> None:
    session = _text(SESSION)
    runbook = _text(RUNBOOK)
    for forbidden in ("--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--disable-gpu-sandbox", "--disable-web-security", "--remote-debugging-port", "--remote-debugging-pipe"):
        assert forbidden not in session
    assert "SOFTWARE_WEBGL_PATH_NOT_ADMISSIBLE_UNDER_CURRENT_SECURITY_CONTRACT" in runbook
    assert "No GPU purchase, VM resize, or cloud mutation is authorized" in runbook


def test_dedicated_identity_and_root_owned_publication_are_fixed() -> None:
    installer = _text(INSTALLER)
    assert "CAPTURE_USER=agent-os-tinkercad-capture" in installer
    assert "INNER_TARGET=/usr/local/libexec/agent-os-tinkercad-browser-session" in installer
    assert "OUTER_TARGET=/usr/local/libexec/agent-os-tinkercad-browser-bootstrap" in installer
    assert 'install -o root -g root -m 0755 "$INNER_SOURCE" "$INNER_TARGET"' in installer
    assert 'install -o root -g root -m 0755 "$outer_tmp" "$OUTER_TARGET"' in installer
    assert '/usr/sbin/runuser -u "$CAPTURE_USER" -- env -i' in installer


def test_installer_keeps_live_activation_separate_from_repository_implementation() -> None:
    installer = _text(INSTALLER)
    assert "Repository implementation does not authorize running this script" in installer
    assert "apt-get install -y --no-install-recommends" in installer
    for forbidden in ("roles/iam", "workloadIdentity", "firewall-rules create", "service-account"):
        assert forbidden not in installer


def test_cleanup_covers_transient_processes_and_preserves_tinkercad_profile() -> None:
    session = _text(SESSION); cleanup = session.split("cleanup() {", 1)[1].split("trap cleanup", 1)[0]
    for pid in ("websockify_pid", "x11vnc_pid", "chromium_pid", "xvfb_pid"):
        assert pid in cleanup
    assert 'rm -f "$XAUTHORITY_FILE"' in cleanup
    assert 'rm -rf "$PROFILE_DIR"' not in cleanup
    assert 'rm -f "$PROFILE_DIR"' not in cleanup
    assert "bounded-ttl-reached" in session


def test_lifecycle_evidence_is_bounded_non_secret_and_never_auth_ready() -> None:
    session = _text(SESSION)
    evidence_lines = "\n".join(line for line in session.splitlines() if "schema_name" in line and "printf" in line)
    for required in ("agent-os-tinkercad-browser-bootstrap-session", "tinkercad-default", "auth_ready_asserted\\\":false", "profile_material_emitted\\\":false", "capture_invoked\\\":false", "scheduler_invoked\\\":false", "external_write_authorized\\\":false", "live_activation_authorized\\\":false"):
        assert required in evidence_lines
    assert "AUTH_READY" not in evidence_lines
    assert "/var/lib/agent-os" not in evidence_lines
    assert "PROFILE_DIR" not in evidence_lines
    for secret_word in ("password", "token", "cookie", "mfa", "credential"):
        assert secret_word not in evidence_lines.lower()


def test_bootstrap_does_not_invoke_capture_replay_scheduler_or_provider() -> None:
    combined = _text(SESSION) + "\n" + _text(INSTALLER)
    for forbidden in ("@puppeteer/replay", "puppeteer", "recording.json", "software-tutorial-capture-v1", "workflow_scheduler", "gemini", "openai", "drive.google", "notion.so"):
        assert forbidden not in combined.lower()
