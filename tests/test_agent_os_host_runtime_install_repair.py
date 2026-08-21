from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-governed-invocation.yml"


def test_repair_uses_sha_pinned_host_checkout_without_scp() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "HOST_RUNTIME_SOURCE_SHA: 038fd018c8d132d07815d6e7e34a4f0eda8d2d8b" in text
    assert "gcloud compute scp" not in text
    assert 'installer="\\$root/08_Tooling/agent-os-execution-service/scripts/install-host-runtime"' in text
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


def test_repair_keeps_diagnostics_bounded_and_non_authorizing() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "host-install.stderr" in text
    assert "path: ${{ runner.temp }}/agent-os-ingress/*.json" in text
    assert '"scheduler_invoked": False' in text
    assert '"execution_authorized": False' in text
    remote = text.split("remote_command=$(cat <<EOF_REMOTE", 1)[1]
    assert "COMMENT_BODY" not in remote
    assert "compute instances stop" not in text
