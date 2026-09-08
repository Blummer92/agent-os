from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
SESSION = ROOT / "08_Tooling/agent-os-execution-service/scripts/agent-os-adobe-browser-session"
INSTALLER = ROOT / "08_Tooling/agent-os-execution-service/scripts/install-adobe-browser-bootstrap"
RUNBOOK = ROOT / "08_Tooling/agent-os-execution-service/docs/ADOBE_BROWSER_BOOTSTRAP.md"
GCE_ADAPTER = (
    ROOT
    / "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/gce_gcloud_adapter.py"
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_fixed_target_and_session_identity_are_not_selectable() -> None:
    session = _text(SESSION)
    installer = _text(INSTALLER)
    runbook = _text(RUNBOOK)
    gce_adapter = _text(GCE_ADAPTER)
    normalized_session = session.replace('\\"', '"')

    assert '[ "$#" -eq 0 ] || fail "arguments are not supported"' in session
    assert '[ "$#" -eq 0 ] || fail "arguments are not supported"' in installer
    assert "browser_session_ref = adobe-express-default" in runbook
    assert '"browser_session_ref":"adobe-express-default"' in normalized_session
    assert 'PROJECT="agent-os-502614"' in gce_adapter
    assert 'ZONE="us-central1-a"' in gce_adapter
    assert 'INSTANCE="agent-os-test"' in gce_adapter
    assert "agent-os-502614 / us-central1-a / agent-os-test" in runbook


def test_browser_profile_display_ports_and_start_url_are_fixed() -> None:
    session = _text(SESSION)

    assert "PROFILE_DIR=$CAPTURE_HOME/.agent-os/browser-profiles/adobe-express" in session
    assert "DISPLAY_ID=:97" in session
    assert "VNC_PORT=5901" in session
    assert "NOVNC_PORT=6080" in session
    assert "SESSION_TTL_SECONDS=1800" in session
    assert "START_URL=https://new.express.adobe.com/" in session
    for forbidden in (
        "${1",
        "${2",
        "getopts",
        "read -r",
        "eval ",
    ):
        assert forbidden not in session


def test_viewer_is_loopback_only_and_clipboard_file_transfer_are_disabled() -> None:
    session = _text(SESSION)

    assert "-localhost" in session
    assert '"127.0.0.1:$NOVNC_PORT"' in session
    assert '"127.0.0.1:$VNC_PORT"' in session
    for required in (
        "-nosel",
        "-noclipboard",
        "-nosetclipboard",
        "-notightfilexfer",
        "-noutrafilexfer",
    ):
        assert required in session


def test_chromium_exposes_no_remote_debugging_or_cdp_transport() -> None:
    session = _text(SESSION)
    installer = _text(INSTALLER)

    assert "--remote-debugging-port" not in session
    assert "--remote-debugging-address" not in session
    assert "--remote-debugging-pipe" not in session
    assert "DevToolsActivePort" not in session
    assert "socat" not in installer


def test_dedicated_capture_identity_and_root_owned_publication_are_fixed() -> None:
    installer = _text(INSTALLER)

    assert "CAPTURE_USER=agent-os-capture" in installer
    assert "INNER_TARGET=/usr/local/libexec/agent-os-adobe-browser-session" in installer
    assert "OUTER_TARGET=/usr/local/libexec/agent-os-adobe-browser-bootstrap" in installer
    assert 'install -o root -g root -m 0755 "$INNER_SOURCE" "$INNER_TARGET"' in installer
    assert 'install -o root -g root -m 0755 "$outer_tmp" "$OUTER_TARGET"' in installer
    assert '/usr/sbin/runuser -u "$CAPTURE_USER" -- env -i' in installer
    assert "gcloud" not in installer
    assert "ssh " not in installer
    assert "compute instances" not in installer


def test_installer_is_explicitly_live_activation_only() -> None:
    installer = _text(INSTALLER)
    runbook = _text(RUNBOOK)

    assert "Repository implementation does not authorize running this script" in installer
    assert "apt-get install -y --no-install-recommends" in installer
    assert "separately authorized" in runbook.lower()
    assert "Repository implementation alone does not authorize" in runbook
    for forbidden in (
        ".github/workflows",
        "roles/iam",
        "workloadIdentity",
        "firewall-rules create",
        "service-account",
    ):
        assert forbidden not in installer


def test_cleanup_covers_every_transient_process_and_preserves_profile() -> None:
    session = _text(SESSION)
    cleanup = session.split("cleanup() {", 1)[1].split("trap cleanup", 1)[0]

    for pid in ("websockify_pid", "x11vnc_pid", "chromium_pid", "xvfb_pid"):
        assert pid in cleanup
    assert 'rm -f "$XAUTHORITY_FILE"' in cleanup
    assert "rm -rf \"$PROFILE_DIR\"" not in cleanup
    assert "rm -f \"$PROFILE_DIR\"" not in cleanup
    assert "SESSION_TTL_SECONDS=1800" in session
    assert "bounded-ttl-reached" in session


def test_lifecycle_evidence_is_bounded_non_secret_and_never_auth_ready() -> None:
    session = _text(SESSION)
    evidence_lines = "\n".join(
        line for line in session.splitlines() if "schema_name" in line and "printf" in line
    )

    for required in (
        "agent-os-adobe-browser-bootstrap-session",
        "adobe-express-default",
        "auth_ready_asserted\\\":false",
        "profile_material_emitted\\\":false",
        "capture_invoked\\\":false",
        "scheduler_invoked\\\":false",
        "external_write_authorized\\\":false",
        "live_activation_authorized\\\":false",
    ):
        assert required in evidence_lines
    assert "AUTH_READY" not in evidence_lines
    assert "/var/lib/agent-os" not in evidence_lines
    assert "PROFILE_DIR" not in evidence_lines
    for secret_word in ("password", "token", "cookie", "mfa", "credential"):
        assert secret_word not in evidence_lines.lower()


def test_bootstrap_does_not_invoke_capture_replay_scheduler_or_provider() -> None:
    session = _text(SESSION)
    installer = _text(INSTALLER)

    combined = session + "\n" + installer
    for forbidden in (
        "@puppeteer/replay",
        "puppeteer",
        "recording.json",
        "software-tutorial-capture-v1",
        "workflow_scheduler",
        "gemini",
        "openai",
        "drive.google",
        "notion.so",
    ):
        assert forbidden not in combined.lower()


def test_runbook_keeps_auth_manual_and_profile_host_local() -> None:
    runbook = _text(RUNBOOK)
    normalized = runbook.lower()

    for required in (
        "manual adobe / sso / mfa",
        "do not automate password entry",
        "do not automate mfa",
        "do not bypass sso",
        "do not inspect, extract, print, or copy cookies/tokens",
        "do not copy the profile directory off-host",
    ):
        assert required in normalized
    assert "Only #932 may determine `AUTH_READY`" in runbook


def test_existing_gce_control_path_is_not_widened_by_bootstrap_contract() -> None:
    gce_adapter = _text(GCE_ADAPTER)

    assert 'PROJECT="agent-os-502614"' in gce_adapter
    assert 'ZONE="us-central1-a"' in gce_adapter
    assert 'INSTANCE="agent-os-test"' in gce_adapter
    assert "GcloudIapAdapter" in gce_adapter
