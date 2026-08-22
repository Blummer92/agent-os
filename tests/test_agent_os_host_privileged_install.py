"""#1341 — the privileged host-install path must never execute user-writable code.

These tests execute the real scripts rather than only asserting on their text:
a refusal string present in a file proves nothing about whether the refusal
actually fires.
"""

from __future__ import annotations

import hashlib
import os
import pwd
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


@pytest.fixture
def trusted_root():
    """A root-owned directory with trusted ancestry.

    pytest's tmp_path sits under /tmp (1777), which the helper correctly rejects
    as an untrusted ancestor, so fixtures that stand in for /usr/local/libexec or
    /var/lib must live directly under /.
    """
    base = Path(tempfile.mkdtemp(prefix="agentos1341-", dir="/"))
    os.chown(base, 0, 0)
    base.chmod(0o755)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _install_helper_at(helper_path: Path, *, dir_mode=0o755, dir_owner=0) -> Path:
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    helper_path.chmod(0o755)
    os.chown(helper_path, 0, 0)
    os.chown(helper_path.parent, dir_owner, 0)
    helper_path.parent.chmod(dir_mode)
    return helper_path


def _staged_copy(tmp_path: Path, staging_root: Path, helper_path: Path) -> Path:
    """Real script, with only the two fixed paths and the build step redirected."""
    text = PRIVILEGED.read_text(encoding="utf-8")
    text = text.replace(
        "STAGING_ROOT=/var/lib/agent-os/host-install-staging",
        f"STAGING_ROOT={staging_root}",
    )
    text = text.replace(
        f"HELPER_PATH={INSTALLED_PRIVILEGED_PATH}",
        f"HELPER_PATH={helper_path}",
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
def test_privileged_staging_is_root_owned_and_not_user_writable(
    tmp_path: Path, trusted_root: Path
) -> None:
    repo, main_sha, _ = _origin_repo(tmp_path)
    staging = trusted_root / "staging"
    helper = _install_helper_at(trusted_root / "libexec" / "agent-os-host-install")
    result = _run_staged(_staged_copy(tmp_path, staging, helper), repo, main_sha)

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
def test_privileged_installer_refuses_a_symlinked_staging_root(
    tmp_path: Path, trusted_root: Path
) -> None:
    repo, main_sha, _ = _origin_repo(tmp_path)
    victim = trusted_root / "victim"
    victim.mkdir()
    staging = trusted_root / "staging"
    staging.symlink_to(victim)
    helper = _install_helper_at(trusted_root / "libexec" / "agent-os-host-install")

    result = _run_staged(_staged_copy(tmp_path, staging, helper), repo, main_sha)

    assert result.returncode == 64
    assert _refusal(result) == "staging root must not be a symlink"
    # The symlink target must be untouched — no rm -rf followed it.
    assert victim.is_dir()
    assert staging.is_symlink()


@pytest.mark.skipif(os.geteuid() != 0, reason="staging assertions require root")
def test_privileged_installer_refuses_source_not_on_canonical_main(
    tmp_path: Path, trusted_root: Path
) -> None:
    repo, _, off_main_sha = _origin_repo(tmp_path)
    staging = trusted_root / "staging"
    helper = _install_helper_at(trusted_root / "libexec" / "agent-os-host-install")
    result = _run_staged(_staged_copy(tmp_path, staging, helper), repo, off_main_sha)

    assert result.returncode == 64
    assert _refusal(result) == "source SHA is not on canonical main"


@pytest.mark.skipif(os.geteuid() != 0, reason="staging assertions require root")
def test_privileged_installer_refuses_a_nonexistent_commit(
    tmp_path: Path, trusted_root: Path
) -> None:
    repo, _, _ = _origin_repo(tmp_path)
    staging = trusted_root / "staging"
    helper = _install_helper_at(trusted_root / "libexec" / "agent-os-host-install")
    result = _run_staged(_staged_copy(tmp_path, staging, helper), repo, "b" * 40)

    assert result.returncode == 64
    assert _refusal(result) == "source SHA is not on canonical main"


@pytest.mark.skipif(os.geteuid() != 0, reason="staging assertions require root")
def test_privileged_staging_is_removed_deterministically(
    tmp_path: Path, trusted_root: Path
) -> None:
    repo, main_sha, _ = _origin_repo(tmp_path)
    staging = trusted_root / "staging"
    helper = _install_helper_at(trusted_root / "libexec" / "agent-os-host-install")
    copy = _staged_copy(tmp_path, staging, helper)
    # Refusal path: the EXIT trap must still clear staging.
    _run_staged(copy, repo, "b" * 40)
    assert not staging.exists()


# --------------------------------------------------------------------------
# S2 — the helper must not be substitutable through its own directory chain
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dir_mode", "label"),
    [(0o777, "world-writable"), (0o775, "group-writable"), (0o757, "other-writable")],
)
@pytest.mark.skipif(os.geteuid() != 0, reason="ownership assertions require root")
def test_privileged_installer_refuses_a_writable_parent_directory(
    tmp_path: Path, trusted_root: Path, dir_mode, label
) -> None:
    """sudo resolves the rule's path at exec time, so a writable parent would let
    the transport identity swap the helper and have root run the replacement."""
    repo, main_sha, _ = _origin_repo(tmp_path)
    helper = _install_helper_at(
        trusted_root / "libexec" / "agent-os-host-install", dir_mode=dir_mode
    )
    staging = trusted_root / "staging"
    result = _run_staged(_staged_copy(tmp_path, staging, helper), repo, main_sha)

    assert result.returncode == 64, label
    assert _refusal(result) == "privileged installer path is untrusted"
    assert not staging.exists(), "must refuse before creating staging"


@pytest.mark.skipif(os.geteuid() != 0, reason="ownership assertions require root")
def test_privileged_installer_refuses_a_non_root_owned_parent_directory(
    tmp_path: Path, trusted_root: Path
) -> None:
    repo, main_sha, _ = _origin_repo(tmp_path)
    nobody = pwd.getpwnam("nobody").pw_uid
    helper = _install_helper_at(
        trusted_root / "libexec" / "agent-os-host-install", dir_owner=nobody
    )
    staging = trusted_root / "staging"
    result = _run_staged(_staged_copy(tmp_path, staging, helper), repo, main_sha)

    assert result.returncode == 64
    assert _refusal(result) == "privileged installer path is untrusted"


@pytest.mark.skipif(os.geteuid() != 0, reason="ownership assertions require root")
def test_privileged_installer_refuses_a_symlinked_parent_directory(
    tmp_path: Path, trusted_root: Path
) -> None:
    repo, main_sha, _ = _origin_repo(tmp_path)
    real = trusted_root / "real-libexec"
    _install_helper_at(real / "agent-os-host-install")
    link = trusted_root / "libexec"
    link.symlink_to(real)
    staging = trusted_root / "staging"
    result = _run_staged(
        _staged_copy(tmp_path, staging, link / "agent-os-host-install"), repo, main_sha
    )

    assert result.returncode == 64
    assert _refusal(result) == "privileged installer path is untrusted"


@pytest.mark.skipif(os.geteuid() != 0, reason="ownership assertions require root")
def test_privileged_installer_refuses_an_untrusted_staging_ancestor(
    tmp_path: Path, trusted_root: Path
) -> None:
    """An ancestor the helper does not own must fail closed, not be rewritten."""
    repo, main_sha, _ = _origin_repo(tmp_path)
    helper = _install_helper_at(trusted_root / "libexec" / "agent-os-host-install")
    lib = trusted_root / "var" / "lib"
    lib.mkdir(parents=True)
    lib.chmod(0o777)
    staging = lib / "agent-os" / "host-install-staging"
    result = _run_staged(_staged_copy(tmp_path, staging, helper), repo, main_sha)

    assert result.returncode == 64
    assert _refusal(result) == "staging path is untrusted"
    assert not staging.exists()
    # The untrusted ancestor must be left exactly as found, never "fixed".
    assert lib.stat().st_mode & 0o777 == 0o777


@pytest.mark.skipif(os.geteuid() != 0, reason="ownership assertions require root")
def test_privileged_installer_normalizes_the_staging_directory_it_owns(
    tmp_path: Path, trusted_root: Path
) -> None:
    """The staging parent is the helper's own directory: it is reset to
    root:root 0755 and then re-verified, rather than refused."""
    repo, main_sha, _ = _origin_repo(tmp_path)
    helper = _install_helper_at(trusted_root / "libexec" / "agent-os-host-install")
    parent = trusted_root / "agent-os"
    parent.mkdir()
    parent.chmod(0o777)
    result = _run_staged(
        _staged_copy(tmp_path, parent / "host-install-staging", helper), repo, main_sha
    )

    assert result.returncode == REACHED_BUILD, result.stderr
    assert parent.stat().st_mode & 0o777 == 0o755
    assert parent.owner() == "root"


def test_privileged_installer_verifies_its_own_path_ancestry() -> None:
    text = PRIVILEGED.read_text(encoding="utf-8")
    assert f"HELPER_PATH={INSTALLED_PRIVILEGED_PATH}" in text
    assert 'require_trusted_ancestry "$HELPER_PATH"' in text
    # Group- and other-writable modes are the ones that must be rejected.
    assert 'case "${_tail%?}" in 2 | 3 | 6 | 7) fail "$_message" ;; esac' in text
    assert 'case "${_tail#?}" in 2 | 3 | 6 | 7) fail "$_message" ;; esac' in text


# --------------------------------------------------------------------------
# S1 — the bootstrap must establish that directory deterministically
# --------------------------------------------------------------------------


def test_workflow_digest_pin_matches_the_tracked_installer() -> None:
    """The route refuses on mismatch, so a stale pin is a silent outage."""
    digest = hashlib.sha256(UNPRIVILEGED.read_bytes()).hexdigest()
    pinned = re.search(
        r"HOST_INSTALL_SCRIPT_SHA256: ([0-9a-f]{64})",
        WORKFLOW.read_text(encoding="utf-8"),
    )
    assert pinned is not None
    assert pinned.group(1) == digest


def test_documented_bootstrap_establishes_the_helper_directory_first() -> None:
    """GNU install does not create a missing parent, and /usr/local/libexec is
    not part of Debian's stock tree."""
    text = DOCS.read_text(encoding="utf-8")
    create = "sudo install -d -o root -g root -m 0755 /usr/local/libexec"
    place = "sudo install -o root -g root -m 0755 \\"
    assert create in text
    assert place in text
    assert text.index(create) < text.index(place), "directory must be created first"


# --------------------------------------------------------------------------
# S3 — preflight is diagnostics, not the security boundary
# --------------------------------------------------------------------------


def test_unprivileged_preflight_is_documented_as_diagnostics_only() -> None:
    script = UNPRIVILEGED.read_text(encoding="utf-8")
    assert "NOT a security boundary" in script
    doc = DOCS.read_text(encoding="utf-8")
    # Collapse whitespace so a markdown reflow across the phrase's line break
    # doesn't defeat this check; it must still require the literal words in order.
    normalized = " ".join(doc.split())
    assert "operator diagnostics, not the security boundary" in normalized
    assert "could skip it entirely" in normalized


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
    # The rule binds one literal authorized SHA (a placeholder an operator
    # substitutes), not a character-class wildcard over any 40-hex value. The
    # pasteable block must contain zero occurrences of that class -- not even
    # as an inert comment, since a copy-pasted comment is still a live risk of
    # confusion in an operational sudoers artifact.
    assert block.count("[0-9a-f]") == 0
    assert block.count("<AUTHORIZED_SOURCE_SHA>") == 1


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
