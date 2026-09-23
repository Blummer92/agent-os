from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[3]
SCRIPTS = ROOT / "08_Tooling/agent-os-execution-service/scripts"
OUTER = SCRIPTS / "agent-os-canva-software-tutorial-capture"
SESSION = SCRIPTS / "agent-os-canva-software-tutorial-capture-session"
INSTALLER = SCRIPTS / "install-canva-software-tutorial-capture"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_capture_entrypoints_accept_no_arguments_or_generic_shell_input() -> None:
    combined = "\n".join(_text(path) for path in (OUTER, SESSION, INSTALLER))

    assert '[ "$#" -eq 0 ] || fail "arguments are not supported"' in _text(OUTER)
    assert '[ "$#" -eq 0 ] || fail "arguments are not supported"' in _text(SESSION)
    assert '[ "$#" -eq 0 ] || fail "arguments are not supported"' in _text(INSTALLER)
    for forbidden in ("eval ", "getopts", "${1", "${2", "--command", "--profile", "--port"):
        assert forbidden not in combined


def test_outer_entrypoint_switches_only_to_fixed_canva_identity_with_clean_environment() -> None:
    outer = _text(OUTER)

    assert "CAPTURE_USER=agent-os-canva-capture" in outer
    assert "CAPTURE_HOME=/var/lib/agent-os/canva-capture-home" in outer
    assert "SESSION_ENTRYPOINT=/usr/local/libexec/agent-os-canva-software-tutorial-capture-session" in outer
    assert 'exec "$RUNUSER" -u "$CAPTURE_USER" -- env -i' in outer
    assert 'HOME="$CAPTURE_HOME"' in outer


def test_session_uses_fixed_node_and_reviewed_capture_entrypoint_only() -> None:
    session = _text(SESSION)

    assert "CAPTURE_USER=agent-os-canva-capture" in session
    assert "NODE=/opt/agent-os/software-tutorial-capture/node/bin/node" in session
    assert "ENTRYPOINT=/opt/agent-os/software-tutorial-capture/package/live_capture_host.mjs" in session
    assert '[ "$(id -un)" = "$CAPTURE_USER" ] || fail "must run as dedicated Canva capture user"' in session
    assert '[ "${HOME:-}" = "$CAPTURE_HOME" ] || fail "capture HOME mismatch"' in session
    assert 'exec "$NODE" "$ENTRYPOINT"' in session


def test_installer_publishes_only_fixed_canva_runtime_and_exact_sudo_command() -> None:
    installer = _text(INSTALLER)

    assert "TRANSPORT_PRINCIPAL=sa_117278680011452280250" in installer
    assert "OUTER_TARGET=/usr/local/libexec/agent-os-canva-software-tutorial-capture" in installer
    assert "SESSION_TARGET=/usr/local/libexec/agent-os-canva-software-tutorial-capture-session" in installer
    assert "SUDOERS_TARGET=/etc/sudoers.d/agent-os-canva-software-tutorial-capture" in installer
    assert "NODE_VERSION=22.16.0" in installer
    assert 'printf \'%s ALL=(root) NOPASSWD: %s\\n\' "$TRANSPORT_PRINCIPAL" "$OUTER_TARGET"' in installer
    assert "/usr/sbin/visudo -c -f \"$candidate\"" in installer
    assert "/usr/sbin/visudo -c" in installer
    for forbidden in ("NOPASSWD: ALL", "workloadIdentity", "firewall-rules", "service-account", "roles/iam"):
        assert forbidden not in installer


def test_installer_verifies_download_and_uses_locked_npm_dependencies() -> None:
    installer = _text(INSTALLER)

    assert "NODE_SHA256=" in installer
    assert "sha256sum -c -" in installer
    assert "package-lock.json" in installer
    assert "PUPPETEER_SKIP_DOWNLOAD=1 npm ci --ignore-scripts --omit=dev" in installer
    assert "live_capture_host.mjs" in installer
    assert "gce_live_capture_request.mjs" in installer
    assert "gce_capture_transport.mjs" in installer


def test_runtime_contract_does_not_transport_browser_credentials_or_profile_bytes() -> None:
    combined = "\n".join(_text(path) for path in (OUTER, SESSION, INSTALLER)).lower()

    for forbidden in ("password=", "token=", "cookie=", "mfa=", "credential="):
        assert forbidden not in combined
    assert "generic_upload_enabled\\\":false" in _text(INSTALLER)
    assert "generic_shell_enabled\\\":false" in _text(INSTALLER)
    assert "profile_material_emitted\\\":false" in _text(INSTALLER)
