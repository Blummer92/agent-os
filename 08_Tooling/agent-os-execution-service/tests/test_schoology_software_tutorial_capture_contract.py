from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[3]
SCRIPTS = ROOT / "08_Tooling/agent-os-execution-service/scripts"
OUTER = SCRIPTS / "agent-os-schoology-software-tutorial-capture"
SESSION = SCRIPTS / "agent-os-schoology-software-tutorial-capture-session"
INSTALLER = SCRIPTS / "install-schoology-software-tutorial-capture"

def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def test_capture_entrypoints_are_executable_and_accept_no_generic_input() -> None:
    assert OUTER.stat().st_mode & 0o111
    assert SESSION.stat().st_mode & 0o111
    assert INSTALLER.stat().st_mode & 0o111
    for path in (OUTER, SESSION, INSTALLER):
        assert '[ "$#" -eq 0 ] || fail "arguments are not supported"' in _text(path)

def test_outer_and_session_are_fixed_to_schoology_identity() -> None:
    outer = _text(OUTER)
    session = _text(SESSION)
    assert "CAPTURE_USER=agent-os-schoology-capture" in outer
    assert "CAPTURE_HOME=/var/lib/agent-os/schoology-capture-home" in outer
    assert "SESSION_ENTRYPOINT=/usr/local/libexec/agent-os-schoology-software-tutorial-capture-session" in outer
    assert "CAPTURE_USER=agent-os-schoology-capture" in session
    assert "ENTRYPOINT=/opt/agent-os/software-tutorial-capture/package/live_capture_host.mjs" in session

def test_installer_publishes_only_fixed_schoology_runtime() -> None:
    installer = _text(INSTALLER)
    assert "PROFILE_DIR=$CAPTURE_HOME/.agent-os/browser-profiles/schoology-kami" in installer
    assert "TRANSPORT_PRINCIPAL=sa_117278680011452280250" in installer
    assert "OUTER_TARGET=/usr/local/libexec/agent-os-schoology-software-tutorial-capture" in installer
    assert "SUDOERS_TARGET=/etc/sudoers.d/agent-os-schoology-software-tutorial-capture" in installer
    assert "NODE_VERSION=22.16.0" in installer
    assert "file_input_bindings.mjs" in installer
    assert "NOPASSWD: ALL" not in installer
