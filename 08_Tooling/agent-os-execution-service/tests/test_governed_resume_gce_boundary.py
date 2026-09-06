"""Cross-boundary regression coverage for #1884 governed-resume host evidence."""

from __future__ import annotations

from dataclasses import dataclass

from agent_os_execution_service.governed_resume_entrypoint import (
    GovernedResumeBindings,
    run_governed_resume,
)
from workflow_scheduler.governance import gce_gcloud_adapter

HANDOFF = "executor-handoff:" + "a" * 64


@dataclass
class Reconstruction:
    status: str = "admitted"
    reason_codes: tuple[str, ...] = ("admitted",)
    pilot_input: object = object()


@dataclass
class PilotResult:
    status: str
    reason_codes: tuple[str, ...]
    result_id: str = "single-issue-pilot:" + "b" * 64
    invocation_id: str = "invocation:1884"
    lease_acquired: bool = True
    lease_released: bool = True
    workspace_created: bool = True
    workspace_filesystem_cleaned: bool = True
    workspace_metadata_cleaned: bool = True
    termination_confirmed: bool = True
    validation_attempted: bool = True
    validation_passed: bool = True


class SshResult:
    returncode = 0
    stderr = ""

    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def _consume_host_output(monkeypatch, pilot: PilotResult):
    output = run_governed_resume(
        ["--handoff-id", HANDOFF],
        bindings=GovernedResumeBindings(
            lambda _: Reconstruction(),
            lambda _: pilot,
        ),
    )
    adapter = gce_gcloud_adapter.GcloudIapAdapter()
    monkeypatch.setattr(adapter, "_ssh", lambda resource, command: SshResult(output))
    return adapter.invoke(
        gce_gcloud_adapter.RESOURCE,
        (
            "/usr/local/libexec/agent-os-governed-resume",
            "--handoff-id",
            HANDOFF,
        ),
    )


def test_real_producer_shape_is_consumed_as_clean_success(monkeypatch) -> None:
    evidence = _consume_host_output(
        monkeypatch,
        PilotResult(status="completed", reason_codes=("lifecycle.proven-complete",)),
    )
    assert evidence.accepted is True
    assert evidence.scheduler_invocation_id == "invocation:1884"
    assert evidence.execution_id == "single-issue-pilot:" + "b" * 64
    assert evidence.terminal_status == "succeeded"
    assert evidence.termination_confirmed is True
    assert evidence.lease_released is True
    assert evidence.cleanup_complete is True
    assert evidence.retained_lease is False
    assert evidence.quarantined is False
    assert evidence.evidence_refs == ("single-issue-pilot:" + "b" * 64,)


def test_real_producer_shape_preserves_quarantine_and_retained_lease(monkeypatch) -> None:
    evidence = _consume_host_output(
        monkeypatch,
        PilotResult(
            status="quarantined",
            reason_codes=("executor.termination-unconfirmed",),
            lease_released=False,
            workspace_filesystem_cleaned=False,
            workspace_metadata_cleaned=False,
            termination_confirmed=False,
            validation_attempted=False,
            validation_passed=False,
        ),
    )
    assert evidence.accepted is True
    assert evidence.terminal_status == "quarantined"
    assert evidence.termination_confirmed is False
    assert evidence.lease_released is False
    assert evidence.cleanup_complete is False
    assert evidence.retained_lease is True
    assert evidence.quarantined is True
