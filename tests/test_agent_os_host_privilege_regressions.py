"""Regression coverage for the independent #1343 privilege-boundary review."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PRIVILEGED = (
    ROOT / "08_Tooling/agent-os-execution-service/scripts/agent-os-host-install"
)
DOCS = ROOT / "08_Tooling/agent-os-execution-service/docs/HOST_RUNTIME_INSTALLATION.md"
INSTALLED_PRIVILEGED_PATH = "/usr/local/libexec/agent-os-host-install"
NOT_ROOT = os.geteuid() != 0


def _active_sudoers_rule() -> str:
    text = DOCS.read_text(encoding="utf-8")
    block = text.split("<!-- sudoers-begin -->", 1)[1].split("<!-- sudoers-end -->", 1)[
        0
    ]
    rules = [
        line.strip() for line in block.splitlines() if line.strip().startswith("sa_")
    ]
    assert len(rules) == 1
    return rules[0]


def test_sudoers_rule_binds_one_literal_authorized_source_sha() -> None:
    rule = _active_sudoers_rule()
    assert "*" not in rule
    assert "[0-9a-f]" not in rule
    assert rule.count("<AUTHORIZED_SOURCE_SHA>") == 1

    allowed = "a" * 40
    denied = "b" * 40
    rendered = rule.replace("<UNIQUE_ID>", "123456789").replace(
        "<AUTHORIZED_SOURCE_SHA>", allowed
    )
    assert rendered.endswith(f"--source-sha {allowed}")
    assert denied not in rendered


def test_privileged_build_uses_hash_pinned_offline_backend() -> None:
    text = PRIVILEGED.read_text(encoding="utf-8")
    assert "SETUPTOOLS_VERSION=83.0.0" in text
    assert (
        "SETUPTOOLS_SHA256="
        "29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3"
    ) in text
    assert "WHEEL_VERSION=0.47.0" in text
    assert (
        "WHEEL_SHA256=212281cab4dff978f6cedd499cd893e1f620791ca6ff7107cf270781e587eced"
    ) in text
    assert "--require-hashes" in text
    assert 'PYTHONPATH="$build_tools" PIP_NO_INDEX=1 python3 -m pip wheel' in text
    assert "--no-build-isolation" in text

    system_install = text.split("PIP_NO_INDEX=1 python3 -m pip install", 1)[1]
    system_install = system_install.split("(", 1)[0]
    assert "--no-index" in system_install
    assert "--no-deps" in system_install


def test_final_install_names_exactly_the_four_built_wheels_and_nothing_else() -> None:
    text = PRIVILEGED.read_text(encoding="utf-8")
    system_install = text.split("PIP_NO_INDEX=1 python3 -m pip install", 1)[1]
    system_install = system_install.split("(", 1)[0]
    for var in (
        '"$capability_wheel"',
        '"$context_wheel"',
        '"$scheduler_wheel"',
        '"$service_wheel"',
    ):
        assert var in system_install
    # No directory or glob install: only the four named, already-verified files.
    assert "*.whl" not in system_install
    assert "$wheel_dir" not in system_install


def test_privileged_python_is_bound_to_qualified_system_interpreter() -> None:
    text = PRIVILEGED.read_text(encoding="utf-8")
    assert "PYTHON=/usr/bin/python3" in text
    assert 'python3() {\n  "$PYTHON" "$@"\n}' in text
    assert "/usr/bin/env python3" not in text


def test_import_verification_is_not_suppressed_and_precedes_publication() -> None:
    """`set -eu` makes the import-check subshell fail closed, but only if
    nothing swallows its exit status and nothing publishes before it runs."""
    text = PRIVILEGED.read_text(encoding="utf-8")
    assert any(line.strip() == "set -eu" for line in text.splitlines())
    import_line = 'env -u PYTHONPATH "$PYTHON" -c \'import agent_os_execution_service'
    assert import_line in text
    # The subshell around the import check must not have its failure discarded.
    subshell = text.split(import_line, 1)[0].rsplit("(", 1)[1] + import_line
    tail = text.split(import_line, 1)[1].split(")", 1)[0]
    assert "|| true" not in tail
    assert "2>/dev/null" not in (subshell + tail)
    # Nothing writes the "installed" evidence or touches TARGET before this line.
    before = text.split(import_line, 1)[0]
    assert '"status": "installed"' not in before
    assert 'sh "$entrypoint_installer"' not in before


def test_import_check_actually_fails_closed_on_a_missing_dependency() -> None:
    """Execute the script's own import-check idiom with a module name guaranteed
    absent and confirm `set -eu` aborts before publication can run."""
    text = PRIVILEGED.read_text(encoding="utf-8")
    real_import = (
        "env -u PYTHONPATH \"$PYTHON\" -c 'import agent_os_execution_service."
        "handoff_discovery_entrypoint; import agent_os_execution_service."
        "governed_resume_entrypoint; import workflow_scheduler.execution."
        "_clone3_cgroup'"
    )
    assert real_import in text
    hostile_import = real_import.replace(
        "agent_os_execution_service.handoff_discovery_entrypoint",
        "agent_os_1341_definitely_missing_module_xyz",
    )
    probe = (
        "set -eu\nPYTHON=/usr/bin/python3\n(\n  cd /\n  "
        f"{hostile_import}\n) >&2\necho UNREACHABLE\n"
    )
    result = subprocess.run(["/bin/sh", "-c", probe], capture_output=True, text=True)
    assert result.returncode != 0
    assert "UNREACHABLE" not in result.stdout


def test_privileged_installer_clears_pythonpath_and_ignores_hostile_path(
    tmp_path: Path,
) -> None:
    """Ambient PYTHONPATH and PATH cannot select privileged Python imports."""
    text = PRIVILEGED.read_text(encoding="utf-8")
    marker = "unset PYTHONPATH"
    assert marker in text, "helper must explicitly clear PYTHONPATH"
    header = text.split(marker, 1)[0] + marker + "\n"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    hostile = fake_bin / "python3"
    hostile.write_text("#!/bin/sh\necho HOSTILE\nexit 97\n", encoding="utf-8")
    hostile.chmod(0o755)
    probe = (
        header + '"$PYTHON" -c \'import sys; '
        'print("HOSTILE" if "/hostile-pythonpath-1341" in sys.path else sys.executable)\''
    )
    result = subprocess.run(
        ["/bin/sh", "-c", probe],
        env={
            **os.environ,
            "PYTHONPATH": "/hostile-pythonpath-1341",
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "/usr/bin/python3"
    assert "HOSTILE" not in result.stdout
    assert text.index(marker) < text.index('PYTHONPATH="$build_tools"'), (
        "the global clear must precede the one intentional, command-scoped re-set"
    )


# --------------------------------------------------------------------------
# exact-SHA sudo authorization: executed against the real sudo policy engine,
# not asserted as text. `sudo -l -U <user> <command...>` reports whether that
# exact invocation would be authorized without actually running it.
# --------------------------------------------------------------------------


def _render_rule(unique_id: str, authorized_sha: str) -> str:
    doc = DOCS.read_text(encoding="utf-8")
    block = doc.split("<!-- sudoers-begin -->", 1)[1].split("<!-- sudoers-end -->", 1)[
        0
    ]
    rule = next(
        line.strip() for line in block.splitlines() if line.strip().startswith("sa_")
    )
    return rule.replace("<UNIQUE_ID>", unique_id).replace(
        "<AUTHORIZED_SOURCE_SHA>", authorized_sha
    )


@pytest.fixture
def rendered_sudo_policy():
    """Install the documented rule, rendered for a throwaway user and one
    authorized SHA, into the real sudoers policy engine on this sandbox --
    never on any live/production host. Yields (username, authorized_sha)."""
    username = f"sa_1341{uuid.uuid4().hex[:12]}"
    authorized_sha = "a" * 40
    subprocess.run(
        ["useradd", "-M", "-N", "-s", "/usr/sbin/nologin", username], check=True
    )
    sudoers_path = Path(f"/etc/sudoers.d/agent-os-1341-regression-{username}")
    stub_dir = Path("/usr/local/libexec")
    stub_dir.mkdir(parents=True, exist_ok=True)
    stub = stub_dir / "agent-os-host-install"
    stub_preexisting = stub.exists()
    stub_backup = None
    try:
        if stub_preexisting:
            stub_backup = stub.read_bytes()
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)

        # The template already begins with the literal "sa_" prefix; pass only
        # the suffix, or the rendered rule names a user that doesn't exist.
        rule = _render_rule(username.removeprefix("sa_"), authorized_sha)
        sudoers_path.write_text(rule + "\n", encoding="utf-8")
        sudoers_path.chmod(0o440)
        check = subprocess.run(
            ["visudo", "-c", "-f", str(sudoers_path)], capture_output=True, text=True
        )
        assert check.returncode == 0, check.stdout + check.stderr

        yield username, authorized_sha
    finally:
        sudoers_path.unlink(missing_ok=True)
        if stub_preexisting:
            stub.write_bytes(stub_backup)
        else:
            stub.unlink(missing_ok=True)
        subprocess.run(["userdel", username], check=False)


def _sudo_allows(username: str, *command: str) -> bool:
    result = subprocess.run(
        ["sudo", "-l", "-U", username, *command],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


@pytest.mark.skipif(NOT_ROOT, reason="sudo policy assertions require root")
def test_sudo_authorizes_exactly_the_one_rendered_invocation(
    rendered_sudo_policy,
) -> None:
    username, authorized_sha = rendered_sudo_policy
    assert _sudo_allows(
        username, INSTALLED_PRIVILEGED_PATH, "--source-sha", authorized_sha
    )


@pytest.mark.skipif(NOT_ROOT, reason="sudo policy assertions require root")
@pytest.mark.parametrize(
    ("label", "make_argv"),
    [
        (
            "another syntactically valid 40-hex SHA",
            lambda sha: ["--source-sha", "b" * 40],
        ),
        ("uppercase SHA", lambda sha: ["--source-sha", sha.upper()]),
        ("41-character SHA", lambda sha: ["--source-sha", sha + "0"]),
        ("39-character SHA", lambda sha: ["--source-sha", sha[:-1]]),
        ("missing argument entirely", lambda sha: []),
        ("flag with no value", lambda sha: ["--source-sha"]),
        (
            "extra trailing argument",
            lambda sha: ["--source-sha", sha, "extra"],
        ),
        (
            "unrelated flag",
            lambda sha: ["--repository-root", "/tmp/evil"],
        ),
    ],
)
def test_sudo_denies_every_syntactically_close_but_wrong_invocation(
    rendered_sudo_policy, label, make_argv
) -> None:
    username, authorized_sha = rendered_sudo_policy
    argv = make_argv(authorized_sha)
    assert not _sudo_allows(username, INSTALLED_PRIVILEGED_PATH, *argv), label


@pytest.mark.skipif(NOT_ROOT, reason="sudo policy assertions require root")
@pytest.mark.parametrize(
    "command",
    [
        ["/usr/bin/true"],
        ["/usr/bin/bash"],
        ["/usr/bin/su"],
        ["/usr/sbin/visudo"],
        ["/usr/bin/apt-get", "install", "-y", "build-essential", "python3-dev"],
        ["/usr/bin/python3", "-m", "pip", "install", "/tmp/evil.whl"],
        ["/usr/bin/sh", "/tmp/agent-os-host-runtime-1238/x"],
    ],
)
def test_sudo_denies_every_unrelated_privileged_command(
    rendered_sudo_policy, command
) -> None:
    username, _ = rendered_sudo_policy
    assert not _sudo_allows(username, *command), command
