"""Bounded-wait admission tests for the #3732 receipt-publication race.

The governed ingress job dispatches validation before it publishes its
receipt artifact, so validation may check before the evidence exists. The
repair (scripts/agent_os_ready_recovery_ingress.py wait_and_verify_ingress)
waits only for the already-identified ingress run and its single receipt
artifact, with fixed bounds, then runs the full verification unchanged.

These tests drive the real wait function against a scripted provider and a
fake clock: no real time passes, no network is touched, and every ordering
is deterministic. The provider exposes no dispatch operation at all, so a
test asserting "no duplicate dispatch" is structural, not behavioral.
"""
from __future__ import annotations

import copy
import io
import json
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _candidate in (REPO_ROOT / "08_Tooling" / "workflow-scheduler" / "src", REPO_ROOT):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from scripts.agent_os_ready_recovery_ingress import (  # noqa: E402
    _GhError,
    wait_and_verify_ingress,
)
from workflow_scheduler.governance.github_issue_comment_ingress import (  # noqa: E402
    admit_issue_comment_event,
)
from workflow_scheduler.governance.ready_recovery_dispatch import (  # noqa: E402
    PullRequestState,
    SourceRunState,
    WorkflowRunSummary,
    execute_dispatch,
)

REPOSITORY = "Blummer92/agent-os"
OWNER = "Blummer92"
SERVICE = "chatgpt-codex-connector[bot]"
HEAD_SHA = "a" * 40
MAIN_SHA = "b" * 40
WORKFLOW_SHA = "b" * 40
WORKFLOW_ID = 314047915
GOVERNED_WORKFLOW_ID = 271828182
SOURCE_RUN_ID = 40150153359
INGRESS_RUN_ID = 40151280000
VALIDATION_RUN_ID = 40151280659
NOW = datetime(2026, 10, 25, 2, 0, 0, tzinfo=timezone.utc)
ARTIFACT_NAME = f"agent-os-ready-recovery-{INGRESS_RUN_ID}-1"
RUN_TIMEOUT = 100.0
RUN_INTERVAL = 10.0
ARTIFACT_TIMEOUT = 30.0
ARTIFACT_INTERVAL = 5.0


class _FakeDispatchClient:
    def get_pull_request(self, pr_number: int) -> PullRequestState:
        return PullRequestState(
            state="open", draft=False, base_ref="main", base_sha=MAIN_SHA,
            head_ref="agent/3723-example", head_sha=HEAD_SHA,
            head_repo_full_name=REPOSITORY,
        )

    def get_main_head_sha(self) -> str:
        return MAIN_SHA

    def get_source_run(self, run_id: int) -> SourceRunState:
        return SourceRunState(
            run_id=run_id, event="pull_request", status="completed",
            conclusion="action_required", head_sha=HEAD_SHA,
            head_branch="agent/3723-example", workflow_id=WORKFLOW_ID,
            workflow_path=".github/workflows/agent-os-validation.yml",
            pr_numbers=(3723,), jobs_total_count=0,
        )

    def get_validation_workflow_id(self) -> int:
        return WORKFLOW_ID

    def list_recovery_dispatch_runs(self) -> list[WorkflowRunSummary]:
        if not hasattr(self, "_called"):
            self._called = True
            return []
        return [WorkflowRunSummary(
            run_id=VALIDATION_RUN_ID,
            url=f"https://github.com/{REPOSITORY}/actions/runs/{VALIDATION_RUN_ID}",
            head_sha=WORKFLOW_SHA, title=f"agent-os-ready-recovery:3723:{HEAD_SHA}",
            created_at=NOW + timedelta(seconds=5), status="in_progress", conclusion=None,
        )]

    def create_recovery_dispatch(self, **kwargs: object) -> None:
        return None


def genuine_receipt_and_transport() -> tuple[dict, dict, str]:
    """Real parser + dispatch output, exactly as the governed ingress job makes it."""
    body = (f"/agent-os recover-ready 3723 {HEAD_SHA} {MAIN_SHA} {WORKFLOW_SHA} "
            f"{SOURCE_RUN_ID}")
    event = {
        "action": "created", "repository": {"full_name": REPOSITORY},
        "issue": {"number": 2410},
        "comment": {"id": 7001, "body": body, "user": {"login": SERVICE}},
        "sender": {"login": SERVICE},
    }
    admitted = admit_issue_comment_event(
        event, expected_repository=REPOSITORY, allowed_actor=OWNER, run_attempt=1,
        ready_recovery_service_actor=SERVICE,
    )
    assert admitted.status == "accepted"
    transport = admitted.to_dict()
    receipt = execute_dispatch(
        transport, _FakeDispatchClient(), ingress_run_id=INGRESS_RUN_ID,
        dispatched_at=NOW, poll_attempts=3, poll_interval_seconds=0,
        sleeper=lambda s: None,
    )
    assert receipt["decision"] == "dispatched"
    return receipt, transport, admitted.logical_trigger_id_or_none


def zip_bytes(receipt: dict, transport: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("receipt.json", json.dumps(receipt))
        zf.writestr("transport.json", json.dumps(transport))
    return buffer.getvalue()


def run_record(*, status: str, conclusion: str | None, actor: str = SERVICE) -> dict:
    return {
        "id": INGRESS_RUN_ID, "workflow_id": GOVERNED_WORKFLOW_ID,
        "event": "issue_comment", "status": status, "conclusion": conclusion,
        "head_branch": "main", "head_sha": MAIN_SHA, "actor": {"login": actor},
    }


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeProvider:
    """Scripted read-only provider. No dispatch operation exists on it."""

    def __init__(self, *, run_timeline, artifact_timeline, zipped: bytes,
                 head_repo: str = REPOSITORY, error_on: str | None = None) -> None:
        self._run_timeline = run_timeline
        self._artifact_timeline = artifact_timeline
        self._zipped = zipped
        self._head_repo = head_repo
        self._error_on = error_on
        self.run_calls = 0
        self.artifact_calls = 0
        self.download_calls = 0
        self.head_repo_calls = 0

    def get_ingress_run(self, run_id: int) -> dict:
        assert run_id == INGRESS_RUN_ID
        self.run_calls += 1
        if self._error_on == "run":
            raise _GhError("HTTP 403: Forbidden", 403)
        return copy.deepcopy(self._run_timeline[min(self.run_calls - 1, len(self._run_timeline) - 1)])

    def list_artifacts(self, run_id: int) -> list[dict]:
        assert run_id == INGRESS_RUN_ID
        self.artifact_calls += 1
        if self._error_on == "artifacts":
            raise _GhError("HTTP 500: Server Error", 500)
        items = self._artifact_timeline[min(self.artifact_calls - 1, len(self._artifact_timeline) - 1)]
        return copy.deepcopy(items)

    def download_artifact(self, artifact_id: int) -> bytes:
        assert artifact_id == 99
        self.download_calls += 1
        if self._error_on == "download":
            raise _GhError("HTTP 404: Not Found", 404)
        return self._zipped

    def get_pr_head_repo(self, pr_number: int) -> str:
        assert pr_number == 3723
        self.head_repo_calls += 1
        if self._error_on == "head_repo":
            raise _GhError("boom")
        return self._head_repo


def wait(provider: FakeProvider, clock: FakeClock, **overrides):
    kwargs = dict(
        repository=REPOSITORY, pr_number=3723, expected_head_sha=HEAD_SHA,
        expected_main_sha=MAIN_SHA, expected_workflow_sha=WORKFLOW_SHA,
        source_run_id=SOURCE_RUN_ID, trigger_id="", ingress_run_id=INGRESS_RUN_ID,
        validation_run_id=VALIDATION_RUN_ID,
        governed_workflow_id=GOVERNED_WORKFLOW_ID, owner_login=OWNER,
        service_actor=SERVICE, run_timeout_seconds=RUN_TIMEOUT,
        run_poll_seconds=RUN_INTERVAL, artifact_timeout_seconds=ARTIFACT_TIMEOUT,
        artifact_poll_seconds=ARTIFACT_INTERVAL, sleeper=clock.sleep,
        monotonic=clock.monotonic,
    )
    kwargs.update(overrides)
    return wait_and_verify_ingress(provider, **kwargs)


def genuine_setup():
    receipt, transport, trigger_id = genuine_receipt_and_transport()
    return zip_bytes(receipt, transport), trigger_id


def completed_provider(zipped: bytes, **kwargs) -> FakeProvider:
    return FakeProvider(
        run_timeline=[run_record(status="completed", conclusion="success")],
        artifact_timeline=[[{"id": 99, "name": ARTIFACT_NAME}]],
        zipped=zipped, **kwargs,
    )


def test_artifact_already_available_verifies() -> None:
    zipped, trigger_id = genuine_setup()
    provider, clock = completed_provider(zipped), FakeClock()
    assert wait(provider, clock, trigger_id=trigger_id) == ("verified", [])
    assert provider.run_calls == 1 and provider.artifact_calls == 1
    assert provider.download_calls == 1 and provider.head_repo_calls == 1
    assert not hasattr(provider, "create_recovery_dispatch")
    assert clock.sleeps == []


def test_artifact_becomes_available_after_validation_starts() -> None:
    zipped, trigger_id = genuine_setup()
    provider = FakeProvider(
        run_timeline=[run_record(status="completed", conclusion="success")],
        artifact_timeline=[[], [{"id": 99, "name": ARTIFACT_NAME}]],
        zipped=zipped,
    )
    clock = FakeClock()
    assert wait(provider, clock, trigger_id=trigger_id) == ("verified", [])
    assert provider.artifact_calls == 2
    assert all(s <= ARTIFACT_INTERVAL for s in clock.sleeps)


def test_ingress_completes_after_validation_starts() -> None:
    """The race itself: validation starts while the ingress job is still
    running; delayed completion plus delayed publication still verify."""
    zipped, trigger_id = genuine_setup()
    provider = FakeProvider(
        run_timeline=[
            run_record(status="in_progress", conclusion=None),
            run_record(status="in_progress", conclusion=None),
            run_record(status="completed", conclusion="success"),
        ],
        artifact_timeline=[[], [{"id": 99, "name": ARTIFACT_NAME}]],
        zipped=zipped,
    )
    clock = FakeClock()
    assert wait(provider, clock, trigger_id=trigger_id) == ("verified", [])
    assert provider.run_calls == 3
    assert all(s <= RUN_INTERVAL for s in clock.sleeps)


def test_artifact_never_appears_fails_closed() -> None:
    zipped, trigger_id = genuine_setup()
    provider = FakeProvider(
        run_timeline=[run_record(status="completed", conclusion="success")],
        artifact_timeline=[[]],
        zipped=zipped,
    )
    clock = FakeClock()
    assert wait(provider, clock, trigger_id=trigger_id) == (
        "failed", ["ingress-artifact-missing"])
    assert provider.download_calls == 0
    assert clock.now >= ARTIFACT_TIMEOUT


def test_ingress_failure_fails_immediately_without_artifact_wait() -> None:
    zipped, trigger_id = genuine_setup()
    provider = FakeProvider(
        run_timeline=[run_record(status="completed", conclusion="failure")],
        artifact_timeline=[[{"id": 99, "name": ARTIFACT_NAME}]],
        zipped=zipped,
    )
    clock = FakeClock()
    assert wait(provider, clock, trigger_id=trigger_id) == (
        "failed", ["ingress-run-not-success"])
    assert provider.artifact_calls == 0 and provider.download_calls == 0
    assert clock.sleeps == []


def test_duplicate_artifacts_fail_immediately() -> None:
    zipped, trigger_id = genuine_setup()
    provider = FakeProvider(
        run_timeline=[run_record(status="completed", conclusion="success")],
        artifact_timeline=[[{"id": 99, "name": ARTIFACT_NAME},
                            {"id": 100, "name": f"{ARTIFACT_NAME}-dup"}]],
        zipped=zipped,
    )
    clock = FakeClock()
    assert wait(provider, clock, trigger_id=trigger_id) == (
        "failed", ["ingress-artifact-duplicate"])
    assert provider.download_calls == 0


def test_malformed_receipt_fails_closed() -> None:
    _, trigger_id = genuine_setup()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("receipt.json", "{}")
    provider = completed_provider(buffer.getvalue())
    clock = FakeClock()
    assert wait(provider, clock, trigger_id=trigger_id) == (
        "failed", ["ingress-receipt-incomplete"])


def test_forged_receipt_run_identity_fails_closed() -> None:
    receipt, transport, trigger_id = genuine_receipt_and_transport()
    receipt["run_id_or_none"] = VALIDATION_RUN_ID + 1
    provider = completed_provider(zip_bytes(receipt, transport))
    clock = FakeClock()
    outcome, reasons = wait(provider, clock, trigger_id=trigger_id)
    assert outcome == "failed"
    assert "receipt-run-id-mismatch" in reasons


def test_stale_head_or_changed_main_fails_closed() -> None:
    zipped, trigger_id = genuine_setup()
    provider = completed_provider(zipped)
    outcome, reasons = wait(provider, FakeClock(), trigger_id=trigger_id,
                            expected_head_sha="c" * 40)
    assert outcome == "failed"
    assert any("head-mismatch" in r for r in reasons)
    provider = completed_provider(zipped)
    outcome, reasons = wait(provider, FakeClock(), trigger_id=trigger_id,
                            expected_main_sha="c" * 40)
    assert outcome == "failed"
    assert any("main-mismatch" in r for r in reasons)


def test_wrong_workflow_or_source_run_identity_fails_closed() -> None:
    zipped, trigger_id = genuine_setup()
    provider = completed_provider(zipped)
    outcome, reasons = wait(provider, FakeClock(), trigger_id=trigger_id,
                            expected_workflow_sha="c" * 40)
    assert outcome == "failed"
    assert any("workflow" in r and "mismatch" in r for r in reasons)
    provider = completed_provider(zipped)
    outcome, reasons = wait(provider, FakeClock(), trigger_id=trigger_id,
                            source_run_id=SOURCE_RUN_ID + 1)
    assert outcome == "failed"
    assert any("source-run-mismatch" in r for r in reasons)


def test_provider_errors_fail_closed() -> None:
    zipped, trigger_id = genuine_setup()
    for error_on, expected in (
        ("run", ["ingress-evidence-lookup-failed", "ingress-evidence-lookup-failed-http-403"]),
        ("artifacts", ["ingress-evidence-lookup-failed", "ingress-evidence-lookup-failed-http-500"]),
        ("download", ["ingress-evidence-lookup-failed", "ingress-evidence-lookup-failed-http-404"]),
        ("head_repo", ["ingress-evidence-lookup-failed"]),
    ):
        provider = completed_provider(zipped, error_on=error_on)
        outcome, reasons = wait(provider, FakeClock(), trigger_id=trigger_id)
        assert (outcome, reasons) == ("failed", expected), error_on


def test_run_timeout_fails_closed_and_stays_bounded() -> None:
    zipped, trigger_id = genuine_setup()
    provider = FakeProvider(
        run_timeline=[run_record(status="in_progress", conclusion=None)],
        artifact_timeline=[[{"id": 99, "name": ARTIFACT_NAME}]],
        zipped=zipped,
    )
    clock = FakeClock()
    assert wait(provider, clock, trigger_id=trigger_id) == (
        "failed", ["ingress-run-wait-timeout"])
    assert provider.download_calls == 0
    assert clock.now >= RUN_TIMEOUT
    assert all(s <= RUN_INTERVAL for s in clock.sleeps)
    assert provider.run_calls <= int(RUN_TIMEOUT / RUN_INTERVAL) + 2


def test_unknown_run_status_fails_closed_immediately() -> None:
    zipped, trigger_id = genuine_setup()
    provider = FakeProvider(
        run_timeline=[run_record(status="waiting", conclusion=None)],
        artifact_timeline=[[{"id": 99, "name": ARTIFACT_NAME}]],
        zipped=zipped,
    )
    clock = FakeClock()
    assert wait(provider, clock, trigger_id=trigger_id) == (
        "failed", ["ingress-run-status-unknown"])
    assert provider.run_calls == 1 and clock.sleeps == []


def test_duplicate_trigger_evidence_cannot_cross_contaminate() -> None:
    """A duplicate trigger's artifact (different ingress run id, hence a
    different name prefix) is not evidence for this validation run, and
    replaying the same wait is side-effect free."""
    zipped, trigger_id = genuine_setup()
    other = f"agent-os-ready-recovery-{INGRESS_RUN_ID + 1}-1"
    provider = FakeProvider(
        run_timeline=[run_record(status="completed", conclusion="success")],
        artifact_timeline=[[{"id": 100, "name": other}]],
        zipped=zipped,
    )
    clock = FakeClock()
    assert wait(provider, clock, trigger_id=trigger_id) == (
        "failed", ["ingress-artifact-missing"])
    assert provider.download_calls == 0
    provider = completed_provider(zipped)
    assert wait(provider, FakeClock(), trigger_id=trigger_id) == ("verified", [])
    assert wait(provider, FakeClock(), trigger_id=trigger_id) == ("verified", [])


def test_fork_head_fails_after_verification() -> None:
    zipped, trigger_id = genuine_setup()
    provider = completed_provider(zipped, head_repo="someone-else/agent-os")
    clock = FakeClock()
    assert wait(provider, clock, trigger_id=trigger_id) == (
        "failed", ["ingress-fork-not-supported"])
    assert provider.download_calls == 1


def test_direct_owner_path_does_not_call_wait() -> None:
    """The wait-and-verify invocation lives only inside the ingress block;
    the direct owner-dispatch branch never invokes it."""
    body = (REPO_ROOT / ".github/workflows/agent-os-validation.yml").read_text()
    assert body.count("wait-and-verify") == 1
    start = body.index('if [ -n "$INGRESS_RUN_ID" ]')
    block = body[start:body.index("# Count immutable GitHub workflow-run records", start)]
    assert "wait-and-verify" in block
    assert "Ready recovery requires repository-owner dispatch" in body
    owner_block = body[:start]
    assert "wait-and-verify" not in owner_block
