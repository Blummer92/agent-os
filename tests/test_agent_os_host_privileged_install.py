"""#1341 — the privileged host-install path must never execute user-writable code.

These tests execute the real scripts rather than only asserting on their text:
a refusal string present in a file proves nothing about whether the refusal
actually fires.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-governed-invocation.yml"
SCRIPTS = ROOT / "08_Tooling/agent-os-execution-service/scripts"
PRIVILEGED = SCRIPTS / "agent-os-host-install"
UNPRIVILEGED = SCRIPTS / "install-host-runtime"
DOCS = ROOT / "08_Tooling/agent-os-execution-service/docs/HOST_RUNTIME_INSTALLATION.md"

INSTALLED_PRIVILEGED_PATH = "/usr/local/libexec/agent-os-host-install"
REFUSAL_PREFIX = "host runtime install refused: "
# Sentinel exit used to stop the real script immediately before the build step,
# after every staging/integrity check has run.
REACHED_BUILD = 111


def _run(argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def _refusal(result) -> str:
    for line in result.stderr.splitlines():
        if line.startswith(REFUSAL_PREFIX):
            return line[len(REFUSAL_PREFIX) :]
    return ""


# --------------------------------------------------------------------------
# argv / identity boundary — no caller input reaches a path
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], "privileged installer argv must be exactly --source-sha <sha>"),
        (
            ["--source-sha"],
            "privileged installer argv must be exactly --source-sha <sha>",
        ),
        (
            ["--source-sha", "a" * 40, "extra"],
            "privileged installer argv must be exactly --source-sha <sha>",
        ),
        (
            ["--repository-root", "/tmp/evil"],
            "privileged installer argv must be exactly --source-sha <sha>",
        ),
        (["--source-sha", "A" * 40], "source SHA must be a lowercase 40-hex commit"),
        (["--source-sha", "a" * 39], "source SHA must be a lowercase 40-hex commit"),
        (
            ["--source-sha", "../../etc/passwd"],
            "source SHA must be a lowercase 40-hex commit",
        ),
        (
            ["--source-sha", "/tmp/evil.whl"],
            "source SHA must be a lowercase 40-hex commit",
        ),
        (
            ["--source-sha", "a" * 40 + " ; id"],
            "source SHA must be a lowercase 40-hex commit",
        ),
    ],
)
def test_privileged_installer_refuses_every_argv_but_one_hex_sha(
    argv, expected
) -> None:
    result = _run(["/bin/sh", str(PRIVILEGED), *argv])
    assert result.returncode == 64
    assert _refusal(result) == expected


@pytest.mark.skipif(os.geteuid() != 0, reason="needs root to drop privileges")
def test_privileged_installer_refuses_to_run_unprivileged(tmp_path: Path) -> None:
    readable = Path(tempfile.mkdtemp(prefix="agent-os-1341-"))
    readable.chmod(0o755)
    copy = readable / "agent-os-host-install"
    shutil.copy2(PRIVILEGED, copy)
    copy.chmod(0o755)
    result = _run(
        ["sudo", "-n", "-u", "nobody", "/bin/sh", str(copy), "--source-sha", "a" * 40]
    )
    shutil.rmtree(readable, ignore_errors=True)
    assert result.returncode == 64
    assert _refusal(result) == "privileged installer must run as root"


# --------------------------------------------------------------------------
# staging boundary — executed against the real script
# --------------------------------------------------------------------------


def _staged_copy(tmp_path: Path, staging_root: Path) -> Path:
    """Real script, with only the staging root and build step redirected."""
    text = PRIVILEGED.read_text(encoding="utf-8")
    text = text.replace(
        "STAGING_ROOT=/var/lib/agent-os/host-install-staging",
        f"STAGING_ROOT={staging_root}",
    )
    marker = "apt-get install -y build-essential python3-dev >&2"
    assert marker in text
    text = text.replace(
        marker,
        f'stat -c "%U:%G:%a" "$STAGING_ROOT" "$checkout"\nexit {REACHED_BUILD}',
    )
    copy = tmp_path / "staged-privileged-install"
    copy.write_text(text, encoding="utf-8")
    copy.chmod(0o755)
    return copy


def _origin_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A local canonical repo: returns (path, main_sha, off_main_sha)."""
    repo = tmp_path / "origin"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout.strip()

    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    (repo / "seed").write_text("seed\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "seed")
    main_sha = git("rev-parse", "HEAD")
    git("checkout", "-q", "-b", "attacker")
    (repo / "payload").write_text("payload\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "payload")
    off_main_sha = git("rev-parse", "HEAD")
    git("checkout", "-q", "main")
    return repo, main_sha, off_main_sha


def _run_staged(copy: Path, repo: Path, sha: str):
    text = copy.read_text(encoding="utf-8").replace(
        "REPOSITORY_URL=https://github.com/Blummer92/agent-os.git",
        f"REPOSITORY_URL=file://{repo}",
    )
    copy.write_text(text, encoding="utf-8")
    return _run(["/bin/sh", str(copy), "--source-sha", sha])


@pytest.mark.skipif(
    os.geteuid() != 0, reason="staging ownership assertions require root"
)
def test_privileged_staging_is_root_owned_and_not_user_writable(tmp_path: Path) -> None:
    repo, main_sha, _ = _origin_repo(tmp_path)
    staging = tmp_path / "staging"
    result = _run_staged(_staged_copy(tmp_path, staging), repo, main_sha)

    assert result.returncode == REACHED_BUILD, result.stderr
    staging_meta, checkout_meta = result.stdout.split()
    # 0700 root:root => the unprivileged transport identity cannot read, write,
    # or traverse the directory privileged execution reads from.
    assert staging_meta == "root:root:700"
    assert checkout_meta.startswith("root:root:")
    # The trap clears staging even on the sentinel exit, so nothing survives for
    # the identity to tamper with afterwards.
    assert not staging.exists()


@pytest.mark.skipif(os.geteuid() != 0, reason="staging assertions require root")
def test_privileged_installer_refuses_a_symlinked_staging_root(tmp_path: Path) -> None:
    repo, main_sha, _ = _origin_repo(tmp_path)
    victim = tmp_path / "victim"
    victim.mkdir()
    staging = tmp_path / "staging"
    staging.symlink_to(victim)

    result = _run_staged(_staged_copy(tmp_path, staging), repo, main_sha)

    assert result.returncode == 64
    assert _refusal(result) == "staging root must not be a symlink"
    # The symlink target must be untouched — no rm -rf followed it.
    assert victim.is_dir()
    assert staging.is_symlink()


@pytest.mark.skipif(os.geteuid() != 0, reason="staging assertions require root")
def test_privileged_installer_refuses_source_not_on_canonical_main(
    tmp_path: Path,
) -> None:
    repo, _, off_main_sha = _origin_repo(tmp_path)
    staging = tmp_path / "staging"
    result = _run_staged(_staged_copy(tmp_path, staging), repo, off_main_sha)

    assert result.returncode == 64
    assert _refusal(result) == "source SHA is not on canonical main"


@pytest.mark.skipif(os.geteuid() != 0, reason="staging assertions require root")
def test_privileged_installer_refuses_a_nonexistent_commit(tmp_path: Path) -> None:
    repo, _, _ = _origin_repo(tmp_path)
    staging = tmp_path / "staging"
    result = _run_staged(_staged_copy(tmp_path, staging), repo, "b" * 40)

    assert result.returncode == 64
    assert _refusal(result) == "source SHA is not on canonical main"


@pytest.mark.skipif(os.geteuid() != 0, reason="staging assertions require root")
def test_privileged_staging_is_removed_deterministically(tmp_path: Path) -> None:
    repo, main_sha, _ = _origin_repo(tmp_path)
    staging = tmp_path / "staging"
    copy = _staged_copy(tmp_path, staging)
    # Refusal path: the EXIT trap must still clear staging.
    _run_staged(copy, repo, "b" * 40)
    assert not staging.exists()


# --------------------------------------------------------------------------
# the unprivileged side holds no privileged step
# --------------------------------------------------------------------------


def test_unprivileged_installer_has_no_privileged_step_of_its_own() -> None:
    text = UNPRIVILEGED.read_text(encoding="utf-8")
    privileged = [
        line.strip()
        for line in text.splitlines()
        if "sudo -n " in line and not line.strip().startswith("#")
    ]
    # Only a policy probe of the exact command, and that same command. The probe
    # must not be a generic `sudo -n true`: the bounded rule does not grant it.
    assert privileged == [
        'sudo -n -l "$PRIVILEGED_INSTALLER" --source-sha "$EXPECTED_SHA" >/dev/null 2>&1 ||',
        'install_json=$(sudo -n "$PRIVILEGED_INSTALLER" --source-sha "$EXPECTED_SHA")',
    ]
    code = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )
    assert "sudo -n true" not in code
    # None of the root-equivalent operations may survive anywhere.
    for banned in (
        "sudo -n apt-get",
        "sudo -n python3 -m pip install",
        "sudo -n sh ",
        "/tmp/agent-os-host-runtime-wheels",
    ):
        assert banned not in text, banned
    assert f"PRIVILEGED_INSTALLER={INSTALLED_PRIVILEGED_PATH}" in text


def test_unprivileged_installer_validates_the_helper_before_invoking_it() -> None:
    text = UNPRIVILEGED.read_text(encoding="utf-8")
    guard = text.split("PRIVILEGED_INSTALLER must already", 1)[0]
    del guard
    checks = text.split('install_json=$(sudo -n "$PRIVILEGED_INSTALLER"', 1)[0]
    assert 'if [ -L "$PRIVILEGED_INSTALLER" ]; then' in checks
    assert '[ -f "$PRIVILEGED_INSTALLER" ] && [ -x "$PRIVILEGED_INSTALLER" ]' in checks
    assert "root:root:700|root:root:750|root:root:755" in checks


def test_unprivileged_installer_rejects_substituted_privileged_evidence() -> None:
    text = UNPRIVILEGED.read_text(encoding="utf-8")
    assert "privileged installer evidence malformed" in text
    assert "privileged installer evidence source mismatch" in text
    assert 'payload.get("source_sha") != os.environ["EXPECTED_SHA"]' in text


# --------------------------------------------------------------------------
# sudo policy shape and reason-code mapping
# --------------------------------------------------------------------------


def _sudoers_block() -> str:
    text = DOCS.read_text(encoding="utf-8")
    marker = "<!-- sudoers-begin -->"
    assert marker in text, "documented sudoers rule is the tested contract"
    return text.split(marker, 1)[1].split("<!-- sudoers-end -->", 1)[0]


def test_documented_sudo_rule_uses_no_wildcard_over_any_path() -> None:
    block = _sudoers_block()
    assert "*" not in block, (
        "a sudoers wildcard would span '/' and escape its directory"
    )
    assert "NOPASSWD: ALL" not in block
    assert "/tmp/" not in block
    assert INSTALLED_PRIVILEGED_PATH in block
    # The only variable part is a fixed-length lowercase-hex character class.
    assert block.count("[0-9a-f]") == 40


def test_documented_sudo_rule_authorizes_nothing_the_old_path_needed() -> None:
    block = _sudoers_block()
    for banned in (
        "apt-get",
        "pip",
        "python3",
        "/bin/sh",
        "/usr/bin/sh",
        "/usr/bin/true",
    ):
        assert banned not in block, banned


def _case_block() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    body = text.split('case "$refusal" in', 1)[1].split("esac", 1)[0]
    return 'case "$refusal" in' + body + "esac"


def _classify(refusal: str) -> str:
    program = (
        'refusal="$1"\n'
        "failure_reason=host-runtime-install-failed\n"
        f"{_case_block()}\n"
        'printf %s "$failure_reason"\n'
    )
    return subprocess.run(
        ["/bin/sh", "-c", program, "sh", refusal],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.mark.parametrize(
    ("refusal", "expected"),
    [
        ("privileged installer unavailable", "host-privileged-installer-unavailable"),
        (
            "privileged installer must be a root-owned regular file",
            "host-privileged-installer-unsafe",
        ),
        ("privileged installer must run as root", "host-privileged-installer-misuse"),
        (
            "privileged installer argv must be exactly --source-sha <sha>",
            "host-privileged-installer-misuse",
        ),
        (
            "source SHA must be a lowercase 40-hex commit",
            "host-privileged-installer-misuse",
        ),
        (
            "privileged installer evidence malformed",
            "host-privileged-installer-evidence-invalid",
        ),
        (
            "privileged installer evidence source mismatch",
            "host-privileged-installer-evidence-invalid",
        ),
        ("staging root must not be a symlink", "host-staging-root-unsafe"),
        ("staging root is not root-owned 0700", "host-staging-root-unsafe"),
        ("staged tree must be root-owned", "host-staged-source-unsafe"),
        (
            "staged entrypoint installer must not be a symlink",
            "host-staged-source-unsafe",
        ),
        ("staged entrypoint installer missing", "host-staged-source-unsafe"),
        ("source SHA is not on canonical main", "host-runtime-source-not-main"),
        ("staged checkout does not match source SHA", "host-runtime-source-mismatch"),
        ("checkout must be on main", "host-runtime-source-not-main"),
        ("checkout does not match EXPECTED_SHA", "host-runtime-source-mismatch"),
        ("passwordless bounded sudo unavailable", "host-passwordless-sudo-unavailable"),
        ("sudo unavailable", "host-sudo-unavailable"),
    ],
)
def test_every_refusal_maps_to_its_own_finite_reason_code(refusal, expected) -> None:
    assert _classify(f"{REFUSAL_PREFIX}{refusal}") == expected


def test_every_refusal_the_scripts_emit_is_classified() -> None:
    """A new refusal must be mapped deliberately, never silently defaulted."""
    emitted = set()
    for script in (PRIVILEGED, UNPRIVILEGED):
        text = script.read_text(encoding="utf-8")
        emitted.update(re.findall(r'fail "([^"$]+)"', text))
        emitted.update(re.findall(rf'{REFUSAL_PREFIX}([^"$\\]+)\\n', text))
    # Preconditions the workflow itself guarantees may stay on the default.
    unmapped = {
        "EXPECTED_SHA must be a lowercase 40-hex commit",
        "REPOSITORY_ROOT must be absolute",
        "REPOSITORY_ROOT must be a git checkout",
    }
    for refusal in sorted(emitted - unmapped):
        assert (
            _classify(f"{REFUSAL_PREFIX}{refusal}") != "host-runtime-install-failed"
        ), refusal


# --------------------------------------------------------------------------
# nothing about execution authority changed
# --------------------------------------------------------------------------


def test_privileged_installer_introduces_no_execution_authority() -> None:
    text = PRIVILEGED.read_text(encoding="utf-8")
    assert '"scheduler_invoked": False' in text
    assert '"execution_authorized": False' in text
    for banned in (
        "gcloud",
        "systemd-run",
        "run_single_issue_pilot",
        "lease",
        "compute instances",
    ):
        assert banned not in text, banned
    # Idempotency proof is preserved: the entrypoint installer runs twice and
    # the resulting hashes must match.
    assert text.count('sh "$entrypoint_installer"') == 2
    assert '[ "$first_hash" = "$second_hash" ]' in text
    assert '[ "$metadata" = "root:root:755" ]' in text


def test_install_governed_resume_is_unchanged_in_contract() -> None:
    text = (SCRIPTS / "install-governed-resume").read_text(encoding="utf-8")
    assert "systemd-run --user --scope -p Delegate=yes" in text
    assert "sudo" not in text


def test_rollback_is_documented_for_staged_and_installed_artifacts_only() -> None:
    text = DOCS.read_text(encoding="utf-8")
    rollback = text.split("## Rollback", 1)[1]
    assert INSTALLED_PRIVILEGED_PATH in rollback
    assert "/var/lib/agent-os" in rollback
    assert "/usr/local/libexec/agent-os-governed-resume" in rollback
    for preserved in ("checkpoint", "ResumePlan", "lease"):
        assert preserved in rollback, preserved
