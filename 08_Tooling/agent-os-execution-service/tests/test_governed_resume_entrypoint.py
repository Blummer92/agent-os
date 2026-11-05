import functools
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest

import agent_os_execution_service.production_governed_resume_factory as production_factory
from agent_os_execution_service.governed_resume_entrypoint import (
    GovernedResumeBindings,
    build_governed_resume_bindings,
    main,
    parse_handoff_argv,
    run_governed_resume,
)
from agent_os_execution_service.invocation_reconstruction import (
    reconstruct_governed_invocation,
)
from workflow_scheduler.execution.single_issue_pilot import run_single_issue_pilot

H = "executor-handoff:" + "a" * 64
PACKAGE_SRC = Path(__file__).parents[1] / "src"
REPOSITORY_ROOT = Path(__file__).parents[3]


class Status(str, Enum):
    ADMITTED = "admitted"
    BLOCKED = "blocked"
    STALE = "stale"
    NEEDS_DECISION = "needs-decision"


@dataclass
class Result:
    status: Status
    reason_codes: tuple[str, ...]
    pilot_input: object | None


@dataclass
class PilotResult:
    status: str = "completed"
    reason_codes: tuple[str, ...] = ("lifecycle.proven-complete",)
    result_id: str = "single-issue-pilot:" + "b" * 64
    invocation_id: str = "invocation:1"
    lease_acquired: bool = True
    lease_released: bool = True
    workspace_created: bool = True
    workspace_filesystem_cleaned: bool = True
    workspace_metadata_cleaned: bool = True
    termination_confirmed: bool = True
    validation_attempted: bool = True
    validation_passed: bool = True


def test_accepts_only_exact_canonical_handoff_argv():
    assert parse_handoff_argv(["--handoff-id", H]) == H
    bad = [
        [], ["--handoff-id"], [H], ["--handoff-id", H, "echo pwned"],
        ["--command", "echo pwned"],
        ["--handoff-id", "executor-handoff:" + "A" * 64],
        ["--handoff-id", "executor-handoff:123"],
    ]
    for argv in bad:
        with pytest.raises(ValueError):
            parse_handoff_argv(argv)


def test_reconstruction_precedes_single_dispatch():
    calls = []
    pilot = object()

    def reconstruct(handoff_id):
        calls.append(("reconstruct", handoff_id))
        return Result(Status.ADMITTED, ("admitted",), pilot)

    def dispatch(value):
        calls.append(("dispatch", value))
        return PilotResult()

    output = run_governed_resume(
        ["--handoff-id", H],
        bindings=GovernedResumeBindings(reconstruct, dispatch),
    )
    assert calls == [("reconstruct", H), ("dispatch", pilot)]
    payload = json.loads(output)
    assert payload["scheduler_dispatch_count"] == 1
    assert payload["status"] == "completed"
    assert payload["terminal_status"] == "succeeded"
    assert payload["accepted"] is True
    assert payload["termination_confirmed"] is True
    assert payload["lease_released"] is True
    assert payload["cleanup_complete"] is True


@pytest.mark.parametrize("status", [Status.BLOCKED, Status.STALE, Status.NEEDS_DECISION])
def test_nonadmitted_result_never_dispatches(status):
    dispatched = []
    result = Result(status, ("example-reason",), None)
    output = run_governed_resume(
        ["--handoff-id", H],
        bindings=GovernedResumeBindings(lambda _: result, dispatched.append),
    )
    payload = json.loads(output)
    assert dispatched == []
    assert payload["status"] == status.value
    assert payload["scheduler_dispatch_count"] == 0
    assert payload["accepted"] is False
    assert payload["terminal_status"] == "blocked-before-execution"
    assert payload["termination_confirmed"] is True
    assert payload["lease_released"] is True
    assert payload["cleanup_complete"] is True


def test_admitted_without_pilot_input_fails_closed():
    dispatched = []
    result = Result(Status.ADMITTED, ("admitted",), None)
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=GovernedResumeBindings(lambda _: result, dispatched.append),
        )
    )
    assert dispatched == []
    assert payload["status"] == "needs-decision"
    assert payload["terminal_status"] == "blocked-before-execution"


def test_dispatch_result_is_not_flattened_to_success():
    reconstruction = Result(Status.ADMITTED, ("admitted",), object())
    pilot = PilotResult(
        status="quarantined",
        reason_codes=("executor.termination-unconfirmed",),
        lease_released=False,
        workspace_filesystem_cleaned=False,
        workspace_metadata_cleaned=False,
        termination_confirmed=False,
        validation_attempted=False,
        validation_passed=False,
    )
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=GovernedResumeBindings(lambda _: reconstruction, lambda _: pilot),
        )
    )
    assert payload["status"] == "quarantined"
    assert payload["terminal_status"] == "quarantined"
    assert payload["quarantined"] is True
    assert payload["retained_lease"] is True
    assert payload["lease_released"] is False
    assert payload["cleanup_complete"] is False
    assert payload["termination_confirmed"] is False


def test_validation_failure_maps_to_existing_host_terminal_vocabulary():
    reconstruction = Result(Status.ADMITTED, ("admitted",), object())
    pilot = PilotResult(
        status="failed",
        reason_codes=("validation.failed",),
        validation_attempted=True,
        validation_passed=False,
    )
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=GovernedResumeBindings(lambda _: reconstruction, lambda _: pilot),
        )
    )
    assert payload["status"] == "failed"
    assert payload["terminal_status"] == "validation-failed"
    assert payload["reason_codes"] == ["validation.failed"]


def test_bounded_evidence_does_not_echo_command_text():
    result = Result(Status.BLOCKED, ("blocked",), None)
    payload = run_governed_resume(
        ["--handoff-id", H],
        bindings=GovernedResumeBindings(lambda _: result, lambda _: None),
    )
    assert "echo" not in payload
    assert set(json.loads(payload)) == {
        "accepted",
        "cleanup_complete",
        "evidence_refs",
        "execution_id",
        "handoff_id",
        "lease_released",
        "quarantined",
        "reason_codes",
        "retained_lease",
        "scheduler_dispatch_count",
        "scheduler_invocation_id",
        "schema",
        "status",
        "terminal_status",
        "termination_confirmed",
    }


def test_main_module_entrypoint_preserves_reconstruction_before_dispatch(capsys):
    calls = []
    pilot = object()

    def reconstruct(handoff_id):
        calls.append(("reconstruct", handoff_id))
        return Result(Status.ADMITTED, ("admitted",), pilot)

    def dispatch(value):
        calls.append(("dispatch", value))
        return PilotResult()

    exit_code = main(
        ["--handoff-id", H],
        bindings=GovernedResumeBindings(reconstruct, dispatch),
    )
    assert exit_code == 0
    assert calls == [("reconstruct", H), ("dispatch", pilot)]
    output = json.loads(capsys.readouterr().out)
    assert output["scheduler_dispatch_count"] == 1
    assert output["terminal_status"] == "succeeded"


@pytest.mark.parametrize("status", [Status.BLOCKED, Status.STALE, Status.NEEDS_DECISION])
def test_main_nonadmitted_input_never_dispatches(status, capsys):
    dispatched = []
    result = Result(status, ("example-reason",), None)
    exit_code = main(
        ["--handoff-id", H],
        bindings=GovernedResumeBindings(lambda _: result, dispatched.append),
    )
    assert exit_code == 0
    assert dispatched == []
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == status.value
    assert payload["scheduler_dispatch_count"] == 0


def test_main_malformed_argv_fails_before_reconstruction():
    reconstruct_calls = []

    def reconstruct(handoff_id):
        reconstruct_calls.append(handoff_id)
        return Result(Status.ADMITTED, ("admitted",), object())

    with pytest.raises(ValueError):
        main(
            ["--command", "echo pwned"],
            bindings=GovernedResumeBindings(reconstruct, lambda _: None),
        )
    assert reconstruct_calls == []


def test_main_rejects_arbitrary_shell_payload_in_handoff_position():
    with pytest.raises(ValueError):
        main(
            ["--handoff-id", H + "; echo pwned"],
            bindings=GovernedResumeBindings(lambda _: None, lambda _: None),
        )


def test_default_main_selects_production_factory_after_argv_validation(monkeypatch, capsys):
    calls = []
    pilot = object()

    def reconstruct(handoff_id):
        calls.append(("reconstruct", handoff_id))
        return Result(Status.ADMITTED, ("admitted",), pilot)

    def dispatch(value):
        calls.append(("dispatch", value))
        return PilotResult()

    def build(handoff_id):
        calls.append(("factory", handoff_id))
        return GovernedResumeBindings(reconstruct, dispatch)

    monkeypatch.setattr(
        production_factory,
        "build_production_governed_resume_bindings_for_handoff",
        build,
    )

    assert main(["--handoff-id", H]) == 0
    assert calls == [("factory", H), ("reconstruct", H), ("dispatch", pilot)]
    output = json.loads(capsys.readouterr().out)
    assert output["scheduler_dispatch_count"] == 1
    assert output["terminal_status"] == "succeeded"


def test_default_main_rejects_malformed_argv_before_production_factory(monkeypatch):
    calls = []
    monkeypatch.setattr(
        production_factory,
        "build_production_governed_resume_bindings_for_handoff",
        lambda handoff_id: calls.append(handoff_id),
    )

    with pytest.raises(ValueError):
        main(["--command", "echo pwned"])

    assert calls == []


def test_build_governed_resume_bindings_reuses_canonical_functions_without_duplication():
    bindings = build_governed_resume_bindings(
        descriptor_loader=lambda handoff_id: None,
        resolver=None,
        lease_reader=None,
        evaluated_at="2026-08-18T00:00:00Z",
        lease=None,
        workspace=None,
        executor=None,
        validator=None,
        cancelled=lambda: False,
    )
    assert isinstance(bindings.reconstruct, functools.partial)
    assert bindings.reconstruct.func is reconstruct_governed_invocation
    assert bindings.reconstruct.keywords["evaluated_at"] == "2026-08-18T00:00:00Z"

    assert isinstance(bindings.dispatch, functools.partial)
    assert bindings.dispatch.func is run_single_issue_pilot


def test_module_invoked_as_cli_executes_and_fails_closed_without_host_configuration():
    """The installed module path executes production selection rather than a no-op."""
    env = os.environ | {"PYTHONPATH": str(PACKAGE_SRC)}
    for name in (
        "AGENT_OS_CHECKPOINT_STORE_ROOT",
        "AGENT_OS_REPOSITORY_ROOT",
        "AGENT_OS_WORKSPACE_PARENT",
        "AGENT_OS_LEASE_DIRECTORY",
    ):
        env.pop(name, None)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_os_execution_service.governed_resume_entrypoint",
            "--handoff-id",
            H,
        ],
        env=env,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "production governed-resume composition failed closed" in proc.stderr
    assert "scheduler_dispatch_count" not in proc.stdout


def test_module_invoked_as_cli_rejects_malformed_argv_before_any_composition():
    env = os.environ | {"PYTHONPATH": str(PACKAGE_SRC)}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_os_execution_service.governed_resume_entrypoint",
            "--command",
            "echo pwned",
        ],
        env=env,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "echo" not in proc.stdout
    assert "expected exactly --handoff-id" in proc.stderr


def test_installer_contract_is_fixed_and_idempotent(tmp_path):
    import hashlib
    import os
    import pathlib
    import stat
    import subprocess

    installer = pathlib.Path(__file__).parents[1] / "scripts" / "install-governed-resume"
    target = tmp_path / "agent-os-governed-resume"
    env = os.environ | {
        "TARGET": str(target),
        "OWNER": subprocess.check_output(["id", "-un"], text=True).strip(),
        "GROUP": subprocess.check_output(["id", "-gn"], text=True).strip(),
        "MODE": "0755",
    }
    subprocess.run([str(installer)], check=True, env=env)
    first = target.read_bytes()
    digest = hashlib.sha256(first).hexdigest()
    subprocess.run([str(installer)], check=True, env=env)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    text = target.read_text()
    assert "systemd-run --user --scope -p Delegate=yes --quiet" in text
    assert "python3 -m agent_os_execution_service.governed_resume_entrypoint" in text
    assert '"$@"' in text


def test_installer_refuses_unrelated_target(tmp_path):
    import os
    import pathlib
    import subprocess

    installer = pathlib.Path(__file__).parents[1] / "scripts" / "install-governed-resume"
    proc = subprocess.run(
        [str(installer)],
        env=os.environ | {"TARGET": str(tmp_path / "not-the-entrypoint")},
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 64
    assert "refusing unexpected target" in proc.stderr


# ---------------------------------------------------------------------------
# Invocation completion receipt (sequential re-delivery duplicate, R-1)
# ---------------------------------------------------------------------------


class FakeCompletionStore:
    """In-memory completion store for entrypoint tests."""

    def __init__(self, *, receipt=None, find_error=None, record_error=None):
        self._receipt = receipt
        self.find_error = find_error
        self.record_error = record_error
        self.find_calls = []
        self.record_calls = []
        self._claims = {}

    def find_completed(self, handoff_id):
        self.find_calls.append(handoff_id)
        if self.find_error is not None:
            raise self.find_error
        return self._receipt

    def record_completed(self, receipt):
        self.record_calls.append(receipt)
        if self.record_error is not None:
            raise self.record_error
        self._receipt = receipt
        return None

    def find_claim(self, handoff_id):
        claim = self._claims.get(handoff_id)
        return dict(claim) if claim is not None else None

    def claim(self, handoff_id, run_id):
        existing = self._claims.get(handoff_id)
        if existing is None:
            self._claims[handoff_id] = {"handoff_id": handoff_id, "run_id": run_id}
            return True
        return existing["run_id"] == run_id

    def release_claim(self, handoff_id, run_id):
        existing = self._claims.get(handoff_id)
        if existing is not None and existing["run_id"] == run_id:
            del self._claims[handoff_id]
            return True
        return False

    def wait_for_completed(self, handoff_id, *, timeout_seconds):
        # In-memory: the receipt either exists now or never will.
        return self.find_completed(handoff_id)


def _completed_receipt(result_id="single-issue-pilot:" + "b" * 64):
    return {
        "schema_version": "1.0",
        "operation": "governed-resume",
        "handoff_id": H,
        "repository": "Blummer92/agent-os",
        "issue_number": 560,
        "invocation_id": "invocation:1",
        "source_sha": "a" * 40,
        "status": "completed",
        "result_id": result_id,
        "recorded_at": "2026-08-17T11:00:00Z",
    }


def _admitted_bindings(dispatch, completion_store=None, claim_wait_seconds=5.0):
    from types import SimpleNamespace

    pilot = SimpleNamespace(
        repository="Blummer92/agent-os",
        issue_numbers=(560,),
        invocation_id="invocation:1",
        source_head_sha="a" * 40,
    )

    def reconstruct(handoff_id):
        return Result(Status.ADMITTED, ("admitted",), pilot)

    return GovernedResumeBindings(
        reconstruct,
        dispatch,
        completion_store=completion_store,
        claim_wait_seconds=claim_wait_seconds,
    )


def test_completed_receipt_blocks_second_dispatch_without_execution():
    dispatched = []
    store = FakeCompletionStore(receipt=_completed_receipt())
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(dispatched.append, completion_store=store),
        )
    )
    assert dispatched == []
    assert payload["status"] == "blocked"
    assert payload["reason_codes"] == ["invocation-already-completed"]
    assert payload["scheduler_dispatch_count"] == 0
    assert payload["accepted"] is False
    assert payload["terminal_status"] == "blocked-before-execution"
    assert store.find_calls == [H]
    assert store.record_calls == []


def test_completed_dispatch_records_the_receipt(tmp_path):
    from agent_os_execution_service.invocation_completion_receipt import (
        InvocationCompletionStore,
    )

    store = InvocationCompletionStore.for_store_root(tmp_path / "store")
    (tmp_path / "store" / "invocations").mkdir(parents=True)
    dispatched = []

    def dispatch(value):
        dispatched.append(value)
        return PilotResult()

    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(dispatch, completion_store=store),
        )
    )
    assert len(dispatched) == 1
    assert payload["status"] == "completed"
    found = store.find_completed(H)
    assert found is not None
    assert found["status"] == "completed"
    assert found["handoff_id"] == H
    assert found["result_id"] == PilotResult().result_id


def test_second_delivery_with_the_same_store_does_not_dispatch(tmp_path):
    from agent_os_execution_service.invocation_completion_receipt import (
        InvocationCompletionStore,
    )

    store = InvocationCompletionStore.for_store_root(tmp_path / "store")
    (tmp_path / "store" / "invocations").mkdir(parents=True)
    dispatched = []

    def dispatch(value):
        dispatched.append(value)
        return PilotResult()

    first = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(dispatch, completion_store=store),
        )
    )
    second = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(dispatch, completion_store=store),
        )
    )
    assert first["status"] == "completed"
    assert first["scheduler_dispatch_count"] == 1
    assert second["status"] == "blocked"
    assert second["reason_codes"] == ["invocation-already-completed"]
    assert second["scheduler_dispatch_count"] == 0
    assert len(dispatched) == 1


def test_failed_dispatch_records_no_receipt(tmp_path):
    from agent_os_execution_service.invocation_completion_receipt import (
        InvocationCompletionStore,
    )

    store = InvocationCompletionStore.for_store_root(tmp_path / "store")
    (tmp_path / "store" / "invocations").mkdir(parents=True)

    def dispatch(value):
        return PilotResult(
            status="failed",
            reason_codes=("validation.failed",),
            validation_attempted=True,
            validation_passed=False,
        )

    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(dispatch, completion_store=store),
        )
    )
    assert payload["status"] == "failed"
    assert store.find_completed(H) is None


def test_unreadable_completion_store_fails_closed_without_dispatch():
    dispatched = []
    store = FakeCompletionStore(find_error=RuntimeError("store unreadable"))
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(dispatched.append, completion_store=store),
        )
    )
    assert dispatched == []
    assert payload["status"] == "needs-decision"
    assert payload["reason_codes"] == ["completion-receipt-unavailable"]
    assert payload["scheduler_dispatch_count"] == 0


def test_receipt_record_failure_is_visible_but_does_not_misreport_success(
    capsys,
):
    dispatched = []
    store = FakeCompletionStore(record_error=RuntimeError("disk full"))

    def dispatch(value):
        dispatched.append(value)
        return PilotResult()

    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(dispatch, completion_store=store),
        )
    )
    assert len(dispatched) == 1
    assert payload["status"] == "completed"
    assert payload["terminal_status"] == "succeeded"
    assert "completion-receipt-unrecorded" in payload["reason_codes"]
    assert "completion receipt unrecorded" in capsys.readouterr().err


def test_no_completion_store_preserves_current_behavior():
    dispatched = []

    def dispatch(value):
        dispatched.append(value)
        return PilotResult()

    for _ in range(2):
        payload = json.loads(
            run_governed_resume(
                ["--handoff-id", H],
                bindings=_admitted_bindings(dispatch),
            )
        )
        assert payload["status"] == "completed"
    assert len(dispatched) == 2


# ---------------------------------------------------------------------------
# Execution claim (post-completion race, hardening)
# ---------------------------------------------------------------------------


def test_claim_is_released_after_a_completed_dispatch(tmp_path):
    from agent_os_execution_service.invocation_completion_receipt import (
        InvocationCompletionStore,
    )

    store = InvocationCompletionStore.for_store_root(tmp_path / "store")
    (tmp_path / "store" / "invocations").mkdir(parents=True)
    dispatched = []

    def dispatch(value):
        dispatched.append(value)
        return PilotResult()

    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(dispatch, completion_store=store),
        )
    )
    assert payload["status"] == "completed"
    assert store.find_claim(H) is None  # recorded, then released
    assert store.find_completed(H) is not None


def test_failed_dispatch_releases_the_claim_and_records_nothing(tmp_path):
    from agent_os_execution_service.invocation_completion_receipt import (
        InvocationCompletionStore,
    )

    store = InvocationCompletionStore.for_store_root(tmp_path / "store")
    (tmp_path / "store" / "invocations").mkdir(parents=True)
    dispatched = []

    def dispatch(value):
        dispatched.append(value)
        return PilotResult(status="failed", reason_codes=("boom",))

    first = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(dispatch, completion_store=store),
        )
    )
    assert first["status"] == "failed"
    assert store.find_claim(H) is None
    assert store.find_completed(H) is None
    # A retry is not blocked by the failed run's claim.
    second = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(dispatch, completion_store=store),
        )
    )
    assert second["status"] == "failed"
    assert len(dispatched) == 2


def test_dispatch_exception_releases_the_claim(tmp_path):
    from agent_os_execution_service.invocation_completion_receipt import (
        InvocationCompletionStore,
    )

    store = InvocationCompletionStore.for_store_root(tmp_path / "store")
    (tmp_path / "store" / "invocations").mkdir(parents=True)

    def dispatch(value):
        raise RuntimeError("pilot exploded")

    with pytest.raises(RuntimeError, match="pilot exploded"):
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(dispatch, completion_store=store),
        )
    assert store.find_claim(H) is None
    assert store.find_completed(H) is None


def test_second_delivery_waits_for_the_owners_receipt_and_blocks():
    class LateReceiptStore(FakeCompletionStore):
        """No receipt at the first check; the owner's receipt lands in the wait."""

        def __init__(self):
            super().__init__()
            self._claims[H] = {"handoff_id": H, "run_id": "a" * 32}
            self._find_calls = 0

        def find_completed(self, handoff_id):
            self._find_calls += 1
            if self._find_calls == 1:
                return None
            return _completed_receipt()

    store = LateReceiptStore()
    dispatched = []
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(
                dispatched.append, completion_store=store, claim_wait_seconds=5.0
            ),
        )
    )
    assert dispatched == []
    assert payload["status"] == "blocked"
    assert payload["reason_codes"] == ["invocation-already-completed"]
    assert payload["scheduler_dispatch_count"] == 0


def test_stale_claim_is_replaced_and_the_delivery_dispatches():
    store = FakeCompletionStore()
    store._claims[H] = {"handoff_id": H, "run_id": "a" * 32}
    dispatched = []

    def dispatch(value):
        dispatched.append(value)
        return PilotResult()

    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(
                dispatch, completion_store=store, claim_wait_seconds=0.0
            ),
        )
    )
    assert payload["status"] == "completed"
    assert len(dispatched) == 1
    assert store.find_claim(H) is None  # released after the completed run
    assert store.find_completed(H) is not None


def test_loser_of_a_claim_replace_returns_blocked_without_dispatching():
    class ContendedStore(FakeCompletionStore):
        """First claim wins; every later claim loses (a replacer won first)."""

        def __init__(self):
            super().__init__()
            self._claims[H] = {"handoff_id": H, "run_id": "a" * 32}
            self._claim_calls = 0

        def claim(self, handoff_id, run_id):
            self._claim_calls += 1
            return False

    store = ContendedStore()
    dispatched = []
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(
                dispatched.append, completion_store=store, claim_wait_seconds=0.0
            ),
        )
    )
    assert dispatched == []
    assert payload["status"] == "blocked"
    assert payload["reason_codes"] == ["invocation-already-claimed"]
    assert payload["scheduler_dispatch_count"] == 0


def test_claim_unavailable_fails_closed_without_dispatch():
    class BrokenClaimStore(FakeCompletionStore):
        def claim(self, handoff_id, run_id):
            raise RuntimeError("claims dir is gone")

    store = BrokenClaimStore()
    dispatched = []
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(dispatched.append, completion_store=store),
        )
    )
    assert dispatched == []
    assert payload["status"] == "needs-decision"
    assert payload["reason_codes"] == ["completion-claim-unavailable"]


def test_receipt_landing_between_claim_and_dispatch_blocks_without_execution():
    class ReceiptDuringClaimStore(FakeCompletionStore):
        """The owner's receipt lands after we acquire the claim."""

        def __init__(self):
            super().__init__()
            self._find_calls = 0

        def find_completed(self, handoff_id):
            self._find_calls += 1
            if self._find_calls <= 1:
                return None
            return _completed_receipt()

    store = ReceiptDuringClaimStore()
    dispatched = []
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=_admitted_bindings(dispatched.append, completion_store=store),
        )
    )
    assert dispatched == []
    assert payload["status"] == "blocked"
    assert payload["reason_codes"] == ["invocation-already-completed"]
    assert store.find_claim(H) is None  # claim released on the blocked path


def test_claim_wait_seconds_is_validated():
    for bad in (-1, float("nan"), float("inf"), True, "5"):
        with pytest.raises(TypeError):
            GovernedResumeBindings(lambda _: None, lambda _: None, claim_wait_seconds=bad)
    assert GovernedResumeBindings(lambda _: None, lambda _: None).claim_wait_seconds == 5.0
    assert (
        GovernedResumeBindings(lambda _: None, lambda _: None, claim_wait_seconds=0).claim_wait_seconds
        == 0
    )


def test_store_without_claim_methods_is_rejected_at_construction():
    class ReceiptOnlyStore:
        def find_completed(self, handoff_id):
            return None

        def record_completed(self, receipt):
            return None

    with pytest.raises(TypeError, match="claim"):
        GovernedResumeBindings(lambda _: None, lambda _: None, completion_store=ReceiptOnlyStore())
