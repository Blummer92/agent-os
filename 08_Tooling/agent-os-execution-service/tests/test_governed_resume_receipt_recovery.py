"""End-to-end tests of docs/GOVERNED_RESUME_RECEIPT_RECOVERY.md.

Each test follows the runbook's steps literally against a temporary
store root, using the real entrypoint and the real store: break the
store, detect the failure, probe, repair, re-deliver, verify dedup.
"""

import json
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_os_execution_service.governed_resume_entrypoint import (
    GovernedResumeBindings,
    run_governed_resume,
)
from agent_os_execution_service.invocation_completion_receipt import (
    InvocationCompletionReceiptError,
    InvocationCompletionStore,
    build_completion_receipt,
)

H2 = "executor-handoff:" + "b" * 64
H3 = "executor-handoff:" + "c" * 64
H4 = "executor-handoff:" + "d" * 64


class Status(str, Enum):
    ADMITTED = "admitted"


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


def _bindings(handoff_id, dispatch, store):
    hex_id = handoff_id.removeprefix("executor-handoff:")
    pilot = SimpleNamespace(
        repository="Blummer92/agent-os",
        issue_numbers=(560,),
        invocation_id="invocation:1",
        source_head_sha="a" * 40,
    )
    return GovernedResumeBindings(
        lambda _: Result(Status.ADMITTED, ("admitted",), pilot),
        dispatch,
        completion_store=store,
        claim_wait_seconds=0.0,
    )


def _store(tmp_path):
    root = tmp_path / "store"
    (root / "invocations").mkdir(parents=True)
    return InvocationCompletionStore.for_store_root(root), root


def test_broken_store_detect_repair_redeliver(tmp_path, capsys):
    store, root = _store(tmp_path)
    dispatched = []

    def dispatch(value):
        dispatched.append(value)
        return PilotResult()

    # Healthy baseline: one delivery completes and records.
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H2], bindings=_bindings(H2, dispatch, store)
        )
    )
    assert payload["status"] == "completed"
    assert store.find_completed(H2) is not None

    # Break the store the way the runbook describes: receipts/ is a file.
    shutil.rmtree(root / "invocations" / "receipts")
    (root / "invocations" / "receipts").write_text("not a directory")

    # Step 1 (runbook): the probe confirms the break.
    with pytest.raises(InvocationCompletionReceiptError):
        store.verify_writable()

    # A delivery of a fresh handoff still completes but warns and records
    # nothing — the run is not misreported as failed.
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H3], bindings=_bindings(H3, dispatch, store)
        )
    )
    assert payload["status"] == "completed"
    assert "completion-receipt-unrecorded" in payload["reason_codes"]
    err = capsys.readouterr().err
    assert "completion receipt unrecorded" in err
    assert f"(store {store.receipts_dir})" in err
    assert store.find_completed(H3) is None

    # Step 2 (runbook): remove the blocking file, recreate the directory.
    (root / "invocations" / "receipts").unlink()
    (root / "invocations" / "receipts").mkdir(mode=0o700)
    store.verify_writable()  # the probe passes again

    # Step 3 (runbook): re-deliver records; the next delivery is blocked.
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H3], bindings=_bindings(H3, dispatch, store)
        )
    )
    assert payload["status"] == "completed"
    assert store.find_completed(H3) is not None
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H3], bindings=_bindings(H3, dispatch, store)
        )
    )
    assert payload["status"] == "blocked"
    assert payload["reason_codes"] == ["invocation-already-completed"]
    assert payload["scheduler_dispatch_count"] == 0


def test_wrong_receipt_conflicts_then_recovers_by_deleting_one_file(tmp_path):
    store, root = _store(tmp_path)
    dispatched = []

    def dispatch(value):
        dispatched.append(value)
        return PilotResult()

    # Plant a receipt whose source SHA does not match the admitted input.
    wrong_input = SimpleNamespace(
        repository="Blummer92/agent-os",
        issue_numbers=(560,),
        invocation_id="invocation:1",
        source_head_sha="f" * 40,
    )
    store.record_completed(
        build_completion_receipt(
            handoff_id=H3, pilot_input=wrong_input, pilot_result=PilotResult()
        )
    )

    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H3], bindings=_bindings(H3, dispatch, store)
        )
    )
    assert payload["status"] == "needs-decision"
    assert payload["reason_codes"] == ["completion-receipt-identity-conflict"]
    assert dispatched == []

    # Runbook recovery: delete that one file only, then re-deliver.
    receipt_path = (
        root
        / "invocations"
        / "receipts"
        / f"governed-resume-completed-{'c' * 64}.json"
    )
    assert receipt_path.is_file()
    receipt_path.unlink()
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H3], bindings=_bindings(H3, dispatch, store)
        )
    )
    assert payload["status"] == "completed"
    assert len(dispatched) == 1
    assert store.find_completed(H3) is not None


def test_corrupt_claim_blocks_then_recovers_by_deleting_one_file(tmp_path):
    store, root = _store(tmp_path)
    dispatched = []

    def dispatch(value):
        dispatched.append(value)
        return PilotResult()

    store.claim(H4, "e" * 32)
    claim_path = (
        root
        / "invocations"
        / "claims"
        / f"governed-resume-claim-{'d' * 64}.json"
    )
    claim_path.write_text("{not json")

    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H4], bindings=_bindings(H4, dispatch, store)
        )
    )
    assert payload["status"] == "needs-decision"
    assert payload["reason_codes"] == ["completion-claim-unavailable"]
    assert dispatched == []

    # Runbook recovery: delete that one claim file only, then re-deliver.
    claim_path.unlink()
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H4], bindings=_bindings(H4, dispatch, store)
        )
    )
    assert payload["status"] == "completed"
    assert len(dispatched) == 1
