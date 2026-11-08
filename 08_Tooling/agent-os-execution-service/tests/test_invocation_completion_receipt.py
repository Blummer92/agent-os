"""Tests for the governed-resume invocation completion receipt store.

Failing-first: the store module does not exist yet. The receipt is the
durable record that closes the sequential re-delivery duplicate (R-1):
one handoff executes the Pilot at most once; a completed receipt makes a
later delivery return without dispatching.
"""

import json
import os
import sys
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from agent_os_execution_service.invocation_completion_receipt import (  # noqa: E402
    InvocationCompletionReceiptError,
    InvocationCompletionStore,
    build_completion_receipt,
)

H = "executor-handoff:" + "a" * 64
H2 = "executor-handoff:" + "c" * 64


def _receipt(handoff_id=H, **overrides):
    body = {
        "schema_version": "1.0",
        "operation": "governed-resume",
        "handoff_id": handoff_id,
        "repository": "Blummer92/agent-os",
        "issue_number": 560,
        "invocation_id": "invocation:1",
        "source_sha": "a" * 40,
        "status": "completed",
        "result_id": "single-issue-pilot:" + "b" * 64,
        "recorded_at": "2026-08-17T11:00:00Z",
    }
    body.update(overrides)
    return body


def _store(tmp_path, root_name="store"):
    # Mirror production: the checkpoint store is Gate 5-initialized, so
    # invocations/ pre-exists; the receipts subdir is created on demand.
    (tmp_path / root_name / "invocations").mkdir(parents=True)
    return InvocationCompletionStore.for_store_root(tmp_path / root_name)


def test_record_then_find_returns_the_same_receipt(tmp_path):
    store = _store(tmp_path)
    receipt = _receipt()
    path = store.record_completed(receipt)
    assert path.is_file()
    found = store.find_completed(H)
    assert found == receipt


def test_find_missing_receipt_returns_none(tmp_path):
    assert _store(tmp_path).find_completed(H) is None


def test_find_on_store_root_without_invocations_dir_returns_none(tmp_path):
    root = tmp_path / "fresh-store"
    root.mkdir()
    assert InvocationCompletionStore.for_store_root(root).find_completed(H) is None


def test_re_recording_an_identical_receipt_is_idempotent(tmp_path):
    store = _store(tmp_path)
    first = store.record_completed(_receipt())
    second = store.record_completed(_receipt())
    assert first == second
    assert store.find_completed(H) == _receipt()


def test_conflicting_receipt_for_the_same_handoff_fails_closed(tmp_path):
    store = _store(tmp_path)
    store.record_completed(_receipt())
    with pytest.raises(InvocationCompletionReceiptError):
        store.record_completed(_receipt(result_id="single-issue-pilot:" + "d" * 64))


def test_record_rejects_a_non_completed_receipt(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(InvocationCompletionReceiptError):
        store.record_completed(_receipt(status="failed"))


def test_record_rejects_a_malformed_handoff_id(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(InvocationCompletionReceiptError):
        store.record_completed(_receipt(handoff_id="not-a-handoff"))


def test_find_rejects_a_receipt_with_a_different_handoff_identity(tmp_path):
    store = _store(tmp_path)
    store.record_completed(_receipt())
    # Corrupt the stored file's handoff identity in place.
    path = next((tmp_path / "store" / "invocations" / "receipts").glob("*.json"))
    body = json.loads(path.read_text())
    body["handoff_id"] = H2
    path.write_text(json.dumps(body))
    with pytest.raises(InvocationCompletionReceiptError):
        store.find_completed(H)


def test_find_rejects_a_malformed_receipt_body(tmp_path):
    store = _store(tmp_path)
    receipts = tmp_path / "store" / "invocations" / "receipts"
    receipts.mkdir(parents=True)
    (receipts / ("governed-resume-completed-" + "a" * 64 + ".json")).write_text(
        "{not json"
    )
    with pytest.raises(InvocationCompletionReceiptError):
        store.find_completed(H)


def test_find_rejects_a_symlinked_receipt(tmp_path):
    store = _store(tmp_path)
    store.record_completed(_receipt())
    receipts = tmp_path / "store" / "invocations" / "receipts"
    target = next(receipts.glob("*.json"))
    real = tmp_path / "real.json"
    real.write_text(target.read_text())
    target.unlink()
    os.symlink(real, target)
    with pytest.raises(InvocationCompletionReceiptError):
        store.find_completed(H)


def test_record_creates_the_receipts_dir_owner_private(tmp_path):
    store = _store(tmp_path)
    store.record_completed(_receipt())
    receipts = tmp_path / "store" / "invocations" / "receipts"
    assert receipts.is_dir()
    assert oct(receipts.stat().st_mode & 0o777) == "0o700"


def test_receipts_for_other_handoffs_are_ignored(tmp_path):
    store = _store(tmp_path)
    store.record_completed(_receipt(handoff_id=H2))
    assert store.find_completed(H) is None
    assert store.find_completed(H2) is not None


# ---------------------------------------------------------------------------
# Execution claims (post-completion race, hardening)
# ---------------------------------------------------------------------------

RUN = "b" * 32
RUN2 = "c" * 32


def test_claim_then_find_returns_the_same_claim(tmp_path):
    store = _store(tmp_path)
    assert store.claim(H, RUN) is True
    found = store.find_claim(H)
    assert found is not None
    assert found["handoff_id"] == H
    assert found["run_id"] == RUN
    assert found["operation"] == "governed-resume-claim"


def test_claim_creates_the_claims_dir_owner_private(tmp_path):
    store = _store(tmp_path)
    store.claim(H, RUN)
    claims = tmp_path / "store" / "invocations" / "claims"
    assert claims.is_dir()
    assert oct(claims.stat().st_mode & 0o777) == "0o700"


def test_second_claim_for_the_same_handoff_returns_false(tmp_path):
    store = _store(tmp_path)
    assert store.claim(H, RUN) is True
    assert store.claim(H, RUN2) is False
    assert store.find_claim(H)["run_id"] == RUN  # first claim still owns it


def test_same_run_reclaiming_is_idempotent(tmp_path):
    store = _store(tmp_path)
    assert store.claim(H, RUN) is True
    assert store.claim(H, RUN) is True


def test_release_claim_only_by_the_owning_run(tmp_path):
    store = _store(tmp_path)
    assert store.claim(H, RUN) is True
    assert store.release_claim(H, RUN2) is False  # another run cannot release
    assert store.find_claim(H) is not None
    assert store.release_claim(H, RUN) is True
    assert store.find_claim(H) is None
    assert store.release_claim(H, RUN) is False  # missing claim is not an error


def test_find_missing_claim_returns_none(tmp_path):
    store = _store(tmp_path)
    assert store.find_claim(H) is None


def test_claim_rejects_a_malformed_run_id(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(InvocationCompletionReceiptError):
        store.claim(H, "not-a-run-id")
    with pytest.raises(InvocationCompletionReceiptError):
        store.claim(H, "A" * 32)


def test_find_rejects_a_malformed_claim_body(tmp_path):
    store = _store(tmp_path)
    store.claim(H, RUN)
    path = tmp_path / "store" / "invocations" / "claims" / f"governed-resume-claim-{'a' * 64}.json"
    path.write_text('{"operation": "governed-resume-claim"}')
    with pytest.raises(InvocationCompletionReceiptError):
        store.find_claim(H)


def test_wait_for_completed_returns_the_receipt_when_it_lands(tmp_path):
    import threading

    store = _store(tmp_path)
    store.claim(H, RUN)

    def record_later():
        import time

        time.sleep(0.2)
        store.record_completed(_receipt())

    thread = threading.Thread(target=record_later)
    thread.start()
    found = store.wait_for_completed(H, timeout_seconds=5.0)
    thread.join()
    assert found is not None
    assert found["status"] == "completed"


def test_wait_for_completed_times_out_with_none(tmp_path):
    store = _store(tmp_path)
    assert store.wait_for_completed(H, timeout_seconds=0.1) is None


def test_wait_for_completed_validates_its_timeout(tmp_path):
    store = _store(tmp_path)
    with pytest.raises((TypeError, ValueError)):
        store.wait_for_completed(H, timeout_seconds=-1)
    with pytest.raises((TypeError, ValueError)):
        store.wait_for_completed(H, timeout_seconds=float("nan"))


def test_record_leaves_no_json_temp_files_behind(tmp_path):
    store = _store(tmp_path)
    store.record_completed(_receipt())
    receipts = tmp_path / "store" / "invocations" / "receipts"
    assert [p for p in receipts.iterdir() if p.suffix == ".json"] == [
        receipts / f"governed-resume-completed-{'a' * 64}.json"
    ]
    assert [p for p in receipts.iterdir() if p.name.startswith(".tmp-")] == []


def test_leftover_tmp_file_is_not_a_receipt(tmp_path):
    store = _store(tmp_path)
    receipts = tmp_path / "store" / "invocations" / "receipts"
    receipts.mkdir(parents=True)
    (receipts / ".tmp-receipt-leftover.tmp").write_text('{"status": "completed"}')
    assert store.find_completed(H) is None
    store.record_completed(_receipt())
    assert store.find_completed(H) is not None


def test_verify_writable_passes_on_a_healthy_store(tmp_path):
    store = _store(tmp_path)
    store.verify_writable()
    assert (tmp_path / "store" / "invocations" / "receipts").is_dir()
    assert (tmp_path / "store" / "invocations" / "claims").is_dir()


def test_verify_writable_fails_when_receipts_is_a_file(tmp_path):
    store_root = tmp_path / "store"
    (store_root / "invocations").mkdir(parents=True)
    (store_root / "invocations" / "receipts").write_text("not a directory")
    store = InvocationCompletionStore.for_store_root(store_root)
    with pytest.raises(InvocationCompletionReceiptError):
        store.verify_writable()


def test_verify_writable_fails_when_claims_is_a_file(tmp_path):
    store_root = tmp_path / "store"
    (store_root / "invocations").mkdir(parents=True)
    (store_root / "invocations" / "claims").write_text("not a directory")
    store = InvocationCompletionStore.for_store_root(store_root)
    with pytest.raises(InvocationCompletionReceiptError):
        store.verify_writable()



@pytest.mark.parametrize("entry", ["receipt", "claim"])
def test_existing_nonregular_store_entry_fails_closed(tmp_path, entry):
    store = _store(tmp_path)
    if entry == "receipt":
        path = store.receipts_dir / f"governed-resume-completed-{'a' * 64}.json"
        lookup = store.find_completed
    else:
        path = store.claims_dir / f"governed-resume-claim-{'a' * 64}.json"
        lookup = store.find_claim
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()
    with pytest.raises(InvocationCompletionReceiptError, match="not a regular file"):
        lookup(H)



@pytest.mark.parametrize("status", ["failed", "quarantined", "blocked", None])
def test_builder_rejects_noncompleted_pilot_results(status):
    input_data = SimpleNamespace(
        repository="Blummer92/agent-os", issue_numbers=(560,),
        invocation_id="invocation:1", source_head_sha="a" * 40,
    )
    result = SimpleNamespace(status=status, result_id="single-issue-pilot:" + "b" * 64)
    with pytest.raises(InvocationCompletionReceiptError, match="not completed"):
        build_completion_receipt(handoff_id=H, pilot_input=input_data, pilot_result=result)


@pytest.mark.parametrize("operation", ["receipt", "claim"])
def test_publication_fsyncs_the_parent_directory(tmp_path, monkeypatch, operation):
    store = _store(tmp_path)
    observed = []
    original_fsync = os.fsync

    def observe(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            observed.append(True)
        return original_fsync(fd)

    monkeypatch.setattr(os, "fsync", observe)
    if operation == "receipt":
        store.record_completed(_receipt())
    else:
        assert store.claim(H, RUN)
    assert observed, "publication must fsync its containing directory"


@pytest.mark.parametrize("operation", ["receipt", "claim"])
def test_publication_fails_closed_when_directory_fsync_fails(tmp_path, monkeypatch, operation):
    store = _store(tmp_path)
    original_fsync = os.fsync

    def failing_directory_sync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected directory fsync failure")
        return original_fsync(fd)

    monkeypatch.setattr(os, "fsync", failing_directory_sync)
    with pytest.raises(InvocationCompletionReceiptError, match="directory could not be persisted"):
        if operation == "receipt":
            store.record_completed(_receipt())
        else:
            store.claim(H, RUN)


def test_wait_for_completed_rejects_infinite_timeout(tmp_path):
    store = _store(tmp_path)
    for timeout in (float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finite"):
            store.wait_for_completed(H, timeout_seconds=timeout)
