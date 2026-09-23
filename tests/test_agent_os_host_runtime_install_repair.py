from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-governed-invocation.yml"
INSTALLER = ROOT / "08_Tooling/agent-os-execution-service/scripts/install-host-runtime"
PRIVILEGED_INSTALLER = (
    ROOT / "08_Tooling/agent-os-execution-service/scripts/agent-os-host-install"
)

# Installer refusal suffix -> the finite reason code the route must report.
# `None` marks a refusal the route deliberately leaves on the generic default
# because the workflow itself controls the precondition.
REFUSAL_REASONS = {
    "installer checksum mismatch": "host-installer-integrity-mismatch",
    "EXPECTED_SHA must be a lowercase 40-hex commit": None,
    "REPOSITORY_ROOT must be absolute": None,
    "REPOSITORY_ROOT must be a git checkout": None,
    "checkout does not match EXPECTED_SHA": "host-runtime-source-mismatch",
    "checkout must be on main": "host-runtime-source-not-main",
    # #1341 privileged-boundary refusals.
    "privileged installer unavailable": "host-privileged-installer-unavailable",
    "privileged installer must be a root-owned regular file": "host-privileged-installer-unsafe",
    "privileged installer must run as root": "host-privileged-installer-misuse",
    "privileged installer argv must be exactly --source-sha <sha>": "host-privileged-installer-misuse",
    "source SHA must be a lowercase 40-hex commit": "host-privileged-installer-misuse",
    "privileged installer evidence malformed": "host-privileged-installer-evidence-invalid",
    "privileged installer evidence source mismatch": "host-privileged-installer-evidence-invalid",
    "staging root must not be a symlink": "host-staging-root-unsafe",
    "staging root is not root-owned 0700": "host-staging-root-unsafe",
    "staging path is untrusted": "host-staging-root-unsafe",
    "privileged installer path is untrusted": "host-privileged-installer-unsafe",
    "staged tree must be root-owned": "host-staged-source-unsafe",
    "staged entrypoint installer must not be a symlink": "host-staged-source-unsafe",
    "staged entrypoint installer missing": "host-staged-source-unsafe",
    "source SHA is not on canonical main": "host-runtime-source-not-main",
    "staged checkout does not match source SHA": "host-runtime-source-mismatch",
    "host OS identity unavailable": "host-os-identity-unavailable",
    "qualified host must be Debian": "host-os-unqualified",
    "qualified host must be Debian 12": "host-os-version-unqualified",
    "sudo unavailable": "host-sudo-unavailable",
    "passwordless bounded sudo unavailable": "host-passwordless-sudo-unavailable",
    "python3 pip unavailable": "host-python-pip-unavailable",
    "expected one reusable-capability-registry wheel": "host-runtime-wheel-shape-invalid",
    "expected one agent-memory-context-manager wheel": "host-runtime-wheel-shape-invalid",
    "expected one workflow-scheduler wheel": "host-runtime-wheel-shape-invalid",
    "expected one agent-os-execution-service wheel": "host-runtime-wheel-shape-invalid",
    "entrypoint installer was not idempotent": "host-entrypoint-idempotency-failed",
    "entrypoint owner/group/mode mismatch": "host-entrypoint-integrity-mismatch",
}

DEFAULT_REASON = "host-runtime-install-failed"


def _case_block() -> str:
    """Extract the workflow's refusal-classification `case` block verbatim."""
    text = WORKFLOW.read_text(encoding="utf-8")
    body = text.split('case "$refusal" in', 1)[1].split("esac", 1)[0]
    return 'case "$refusal" in' + body + "esac"


def _classify(refusal: str) -> str:
    """Run the workflow's own `case` block against one refusal line."""
    program = (
        'refusal="$1"\n'
        f"failure_reason={DEFAULT_REASON}\n"
        f"{_case_block()}\n"
        'printf %s "$failure_reason"\n'
    )
    completed = subprocess.run(
        ["/bin/sh", "-c", program, "sh", refusal],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def test_repair_uses_sha_pinned_host_checkout_without_scp() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "HOST_RUNTIME_SOURCE_SHA: 36ccd1715b8b11e30f8d92196b8e7f0791c10547" in text
    assert "gcloud compute scp" not in text
    assert (
        'installer="\\$root/08_Tooling/agent-os-execution-service/scripts/install-host-runtime"'
        in text
    )
    assert 'git -C "\\$root" checkout --quiet -B main $HOST_RUNTIME_SOURCE_SHA' in text
    assert "installer checksum mismatch" in text


def test_repair_maps_installer_refusals_to_finite_reason_codes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for reason in (
        "host-installer-integrity-mismatch",
        "host-runtime-source-mismatch",
        "host-runtime-source-not-main",
        "host-os-identity-unavailable",
        "host-os-unqualified",
        "host-os-version-unqualified",
        "host-sudo-unavailable",
        "host-passwordless-sudo-unavailable",
        "host-python-pip-unavailable",
        "host-runtime-wheel-shape-invalid",
        "host-entrypoint-idempotency-failed",
        "host-entrypoint-integrity-mismatch",
    ):
        assert reason in text
    assert '"reason_codes": [os.environ["FAILURE_REASON"]]' in text


def test_repair_classifies_every_installer_refusal_to_its_own_reason_code() -> None:
    """Execute the route's own `case` block; string presence is not a mapping."""
    for suffix, expected in REFUSAL_REASONS.items():
        refusal = f"host runtime install refused: {suffix}"
        assert _classify(refusal) == (expected or DEFAULT_REASON), suffix


def test_repair_never_shadows_passwordless_sudo_with_generic_sudo() -> None:
    """`*"sudo unavailable"` also matches the passwordless refusal, so the
    specific pattern must be ordered first or the finite reason is wrong."""
    assert (
        _classify("host runtime install refused: passwordless bounded sudo unavailable")
        == "host-passwordless-sudo-unavailable"
    )
    assert (
        _classify("host runtime install refused: sudo unavailable")
        == "host-sudo-unavailable"
    )


def test_repair_defaults_unknown_refusals_instead_of_guessing() -> None:
    assert _classify("host runtime install refused: something new") == DEFAULT_REASON
    assert _classify("") == DEFAULT_REASON


def test_repair_covers_every_refusal_the_installer_can_emit() -> None:
    """A new installer refusal must be classified deliberately, not silently."""
    emitted = set()
    for script in (INSTALLER, PRIVILEGED_INSTALLER):
        text = script.read_text(encoding="utf-8")
        emitted.update(re.findall(r'fail "([^"$]+)"', text))
        emitted.update(re.findall(r'host runtime install refused: ([^"$\\]+)\\n', text))
        # Messages handed to the trusted-path guards rather than to fail()
        # directly. These lines nest shell quoting, so parse them as shell.
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith(
                ("require_trusted_path ", "require_trusted_ancestry ")
            ):
                continue
            try:
                message = shlex.split(stripped)[-1]
            except ValueError:
                continue
            if "$" not in message:
                emitted.add(message)
    emitted.add("installer checksum mismatch")  # emitted by the remote preamble
    assert emitted == set(REFUSAL_REASONS)


def test_repair_keeps_diagnostics_bounded_and_non_authorizing() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "host-install.stderr" in text
    assert "path: ${{ runner.temp }}/agent-os-ingress/*.json" in text
    assert '"scheduler_invoked": False' in text
    assert '"execution_authorized": False' in text
    remote = text.split("remote_command=$(cat <<EOF_REMOTE", 1)[1]
    assert "COMMENT_BODY" not in remote
    assert "compute instances stop" not in text
