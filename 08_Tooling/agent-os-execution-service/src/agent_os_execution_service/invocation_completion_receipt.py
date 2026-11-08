"""Durable completion receipts and execution claims for governed resume.

One handoff executes the Pilot at most once across sequential deliveries.
After a dispatch returns a ``completed`` Pilot result, ``run_governed_resume``
records a receipt here; on a later delivery of the same handoff, a completed
receipt returns the caller without dispatching. This is the governed-resume
analogue of the gate2 fixed-pilot B10 replay receipt, scoped to the Pilot's
handoff.

Layout reuses the existing convention
``$AGENT_OS_CHECKPOINT_STORE_ROOT/invocations/receipts/`` (the same
directory the gate2 controller uses). One file per handoff:
``governed-resume-completed-<handoff-hex>.json``. Writes are atomic
(temp file + ``os.link`` O_EXCL + readback, mirroring the checkpoint
store): recording an identical receipt twice is an idempotent success;
different content under one handoff is an integrity conflict.

The store also holds one durable execution claim per handoff under the
sibling directory ``invocations/claims/``:
``governed-resume-claim-<handoff-hex>.json``. A delivery claims before
dispatching; a later delivery that finds another delivery's claim waits
briefly for a receipt and otherwise fails closed without dispatching.
Claims close the post-completion race in which the Pilot releases its
lease before the receipt is published. Claims never decide authorization:
they record only that one delivery is executing (or was executing) for
one immutable handoff. A crashed or uncertain delivery requires operator
reconciliation; a timeout does not prove the claim stale.

Temporary files use the ``.tmp`` suffix (never ``.json``): the gate2 probe
scan reads every ``.json`` file in ``receipts/``, so a leftover temp file
must never be scannable as a receipt.

The store never decides authorization: it records only that a completed
execution for one immutable handoff already happened. Failed, quarantined,
or blocked runs record nothing and remain re-admissible.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT_SCHEMA_VERSION = "1.0"
RECEIPT_OPERATION = "governed-resume"
CLAIM_OPERATION = "governed-resume-claim"
#: Filename namespace owned by this store. Other receipt scanners in the
#: same directory (notably the gate2 probe scan) skip files under this
#: prefix: they are never that scanner's evidence, and a malformed one
#: must not break an unrelated scan. Files under any other name keep the
#: scanner's established fail-closed behavior.
GOVERNED_ARTIFACT_PREFIX = "governed-resume-"
INVOCATIONS_SUBDIR = "invocations"
RECEIPTS_SUBDIR = "receipts"
CLAIMS_SUBDIR = "claims"
_RECEIPT_PREFIX = "governed-resume-completed-"
_CLAIM_PREFIX = "governed-resume-claim-"
_HANDOFF_RE = re.compile(r"\Aexecutor-handoff:[0-9a-f]{64}\Z")
_RUN_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")
_SHA40_RE = re.compile(r"\A[0-9a-f]{40}\Z")
_TIMESTAMP_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")

_RECEIPT_FIELDS = (
    "schema_version",
    "operation",
    "handoff_id",
    "repository",
    "issue_number",
    "invocation_id",
    "source_sha",
    "status",
    "result_id",
    "recorded_at",
)

_CLAIM_FIELDS = (
    "schema_version",
    "operation",
    "handoff_id",
    "run_id",
    "claimed_at",
)


class InvocationCompletionReceiptError(RuntimeError):
    """The completion receipt store is unreadable, malformed, or conflicting."""


def _canonical_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_receipt_body(receipt: object) -> dict[str, Any]:
    if type(receipt) is not dict:
        raise InvocationCompletionReceiptError("completion receipt must be a mapping")
    for field in _RECEIPT_FIELDS:
        if field not in receipt:
            raise InvocationCompletionReceiptError(
                f"completion receipt is missing {field}"
            )
    if receipt["schema_version"] != RECEIPT_SCHEMA_VERSION:
        raise InvocationCompletionReceiptError("unsupported completion receipt schema")
    if receipt["operation"] != RECEIPT_OPERATION:
        raise InvocationCompletionReceiptError("completion receipt operation mismatch")
    handoff_id = receipt["handoff_id"]
    if type(handoff_id) is not str or _HANDOFF_RE.fullmatch(handoff_id) is None:
        raise InvocationCompletionReceiptError("completion receipt handoff is invalid")
    if type(receipt["repository"]) is not str or not receipt["repository"]:
        raise InvocationCompletionReceiptError("completion receipt repository is invalid")
    issue_number = receipt["issue_number"]
    if type(issue_number) is not int or isinstance(issue_number, bool):
        raise InvocationCompletionReceiptError("completion receipt issue is invalid")
    if type(receipt["invocation_id"]) is not str or not receipt["invocation_id"]:
        raise InvocationCompletionReceiptError(
            "completion receipt invocation is invalid"
        )
    source_sha = receipt["source_sha"]
    if type(source_sha) is not str or _SHA40_RE.fullmatch(source_sha) is None:
        raise InvocationCompletionReceiptError("completion receipt source SHA is invalid")
    if receipt["status"] != "completed":
        raise InvocationCompletionReceiptError("completion receipt is not completed")
    if type(receipt["result_id"]) is not str or not receipt["result_id"]:
        raise InvocationCompletionReceiptError("completion receipt result is invalid")
    recorded_at = receipt["recorded_at"]
    if type(recorded_at) is not str or _TIMESTAMP_RE.fullmatch(recorded_at) is None:
        raise InvocationCompletionReceiptError("completion receipt timestamp is invalid")
    return receipt


def build_completion_receipt(
    *,
    handoff_id: str,
    pilot_input: object,
    pilot_result: object,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Build the receipt binding one admitted pilot input to its completed outcome."""
    if type(handoff_id) is not str or _HANDOFF_RE.fullmatch(handoff_id) is None:
        raise InvocationCompletionReceiptError("handoff id is invalid")
    issue_numbers = getattr(pilot_input, "issue_numbers", None)
    if (
        type(issue_numbers) is not tuple
        or len(issue_numbers) != 1
        or type(issue_numbers[0]) is not int
    ):
        raise InvocationCompletionReceiptError("pilot input must carry exactly one issue")
    repository = getattr(pilot_input, "repository", None)
    invocation_id = getattr(pilot_input, "invocation_id", None)
    source_sha = getattr(pilot_input, "source_head_sha", None)
    result_id = getattr(pilot_result, "result_id", None)
    status = getattr(pilot_result, "status", None)
    if getattr(status, "value", status) != "completed":
        raise InvocationCompletionReceiptError("pilot result is not completed")
    if type(repository) is not str or not repository:
        raise InvocationCompletionReceiptError("pilot input repository is invalid")
    if type(invocation_id) is not str or not invocation_id:
        raise InvocationCompletionReceiptError("pilot input invocation is invalid")
    if type(source_sha) is not str or _SHA40_RE.fullmatch(source_sha) is None:
        raise InvocationCompletionReceiptError("pilot input source SHA is invalid")
    if type(result_id) is not str or not result_id:
        raise InvocationCompletionReceiptError("pilot result id is invalid")
    if recorded_at is None:
        recorded_at = _canonical_now()
    elif type(recorded_at) is not str or _TIMESTAMP_RE.fullmatch(recorded_at) is None:
        raise InvocationCompletionReceiptError("recorded_at timestamp is invalid")
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "operation": RECEIPT_OPERATION,
        "handoff_id": handoff_id,
        "repository": repository,
        "issue_number": issue_numbers[0],
        "invocation_id": invocation_id,
        "source_sha": source_sha,
        "status": "completed",
        "result_id": result_id,
        "recorded_at": recorded_at,
    }


def _validate_claim_body(claim: object) -> dict[str, Any]:
    if type(claim) is not dict:
        raise InvocationCompletionReceiptError("execution claim must be a mapping")
    for field in _CLAIM_FIELDS:
        if field not in claim:
            raise InvocationCompletionReceiptError(
                f"execution claim is missing {field}"
            )
    if claim["schema_version"] != RECEIPT_SCHEMA_VERSION:
        raise InvocationCompletionReceiptError("unsupported execution claim schema")
    if claim["operation"] != CLAIM_OPERATION:
        raise InvocationCompletionReceiptError("execution claim operation mismatch")
    handoff_id = claim["handoff_id"]
    if type(handoff_id) is not str or _HANDOFF_RE.fullmatch(handoff_id) is None:
        raise InvocationCompletionReceiptError("execution claim handoff is invalid")
    run_id = claim["run_id"]
    if type(run_id) is not str or _RUN_ID_RE.fullmatch(run_id) is None:
        raise InvocationCompletionReceiptError("execution claim run id is invalid")
    claimed_at = claim["claimed_at"]
    if type(claimed_at) is not str or _TIMESTAMP_RE.fullmatch(claimed_at) is None:
        raise InvocationCompletionReceiptError("execution claim timestamp is invalid")
    return claim


def build_execution_claim(
    *,
    handoff_id: str,
    run_id: str,
    claimed_at: str | None = None,
) -> dict[str, Any]:
    """Build the claim one delivery publishes before dispatching."""
    if type(handoff_id) is not str or _HANDOFF_RE.fullmatch(handoff_id) is None:
        raise InvocationCompletionReceiptError("handoff id is invalid")
    if type(run_id) is not str or _RUN_ID_RE.fullmatch(run_id) is None:
        raise InvocationCompletionReceiptError("run id is invalid")
    if claimed_at is None:
        claimed_at = _canonical_now()
    elif type(claimed_at) is not str or _TIMESTAMP_RE.fullmatch(claimed_at) is None:
        raise InvocationCompletionReceiptError("claimed_at timestamp is invalid")
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "operation": CLAIM_OPERATION,
        "handoff_id": handoff_id,
        "run_id": run_id,
        "claimed_at": claimed_at,
    }


def _write_temp_file(directory: Path, payload: bytes) -> str:
    """Write payload to a temp file (suffix ``.tmp``) and return its path.

    The ``.tmp`` suffix is load-bearing: receipt scanners read every
    ``.json`` file, so a leftover temp must never look like a receipt.
    On any failure the temp file is removed; on success the caller owns it.
    """
    temp_name: str | None = None
    owned = False
    try:
        descriptor, temp_name = tempfile.mkstemp(
            dir=os.fspath(directory), prefix=".tmp-receipt-", suffix=".tmp"
        )
        owned = True
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        owned = False  # fdopen closed the descriptor; the temp file is complete
        return temp_name
    except OSError as exc:
        raise InvocationCompletionReceiptError(
            "completion store could not be written"
        ) from exc
    finally:
        if owned:
            try:
                os.close(descriptor)
            except OSError:
                pass
            if temp_name is not None:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass


def _sync_parent_directory(path: Path) -> None:
    """Persist the directory entry; a durable payload alone is insufficient."""
    try:
        descriptor = os.open(os.fspath(path.parent), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise InvocationCompletionReceiptError(
            "completion store directory could not be persisted"
        ) from exc


def _link_or_exists(temp_name: str, final: Path) -> bool:
    """Publish a temp file with ``os.link`` O_EXCL; True if linked.

    Returns False when the destination already exists (the caller decides
    what an existing file means). A symlinked destination is corruption
    and raises, as is any other publish failure.
    """
    try:
        os.link(temp_name, os.fspath(final))
    except FileExistsError:
        if final.is_symlink():
            raise InvocationCompletionReceiptError(
                "completion store entry is a symlink"
            ) from None
        return False
    except OSError as exc:
        raise InvocationCompletionReceiptError(
            "completion store entry could not be published"
        ) from exc
    _sync_parent_directory(final)
    return True


def _read_back(final: Path, expected: dict[str, Any], *, what: str) -> None:
    try:
        read_back = json.loads(final.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise InvocationCompletionReceiptError(
            f"{what} readback failed"
        ) from exc
    if read_back != expected:
        raise InvocationCompletionReceiptError(f"{what} readback mismatch")


def _discard_temp(temp_name: str | None) -> None:
    if temp_name is not None:
        try:
            os.unlink(temp_name)
        except OSError:
            pass


def _read_regular_store_entry(path: Path, *, what: str) -> bytes | None:
    """An absent entry is retryable; an existing non-file entry is corruption."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InvocationCompletionReceiptError(f"{what} is unreadable") from exc
    if not stat.S_ISREG(mode):
        raise InvocationCompletionReceiptError(f"{what} is not a regular file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise InvocationCompletionReceiptError(f"{what} is unreadable") from exc


class InvocationCompletionStore:
    """One completion receipt and one execution claim per handoff."""

    def __init__(self, receipts_dir: Path | str) -> None:
        if isinstance(receipts_dir, str):
            if not receipts_dir.strip():
                raise TypeError("receipts_dir must identify a path")
            receipts_dir = Path(receipts_dir)
        elif not isinstance(receipts_dir, Path):
            raise TypeError("receipts_dir must be a path")
        self._receipts_dir = receipts_dir
        self._claims_dir = receipts_dir.parent / CLAIMS_SUBDIR

    @property
    def receipts_dir(self) -> Path:
        return self._receipts_dir

    @property
    def claims_dir(self) -> Path:
        return self._claims_dir

    @classmethod
    def for_store_root(cls, store_root: Path | str) -> "InvocationCompletionStore":
        if isinstance(store_root, str):
            if not store_root.strip():
                raise TypeError("store_root must identify a path")
            store_root = Path(store_root)
        elif not isinstance(store_root, Path):
            raise TypeError("store_root must be a path")
        return cls(store_root / INVOCATIONS_SUBDIR / RECEIPTS_SUBDIR)

    def _receipt_path(self, handoff_id: str) -> Path:
        if type(handoff_id) is not str or _HANDOFF_RE.fullmatch(handoff_id) is None:
            raise InvocationCompletionReceiptError("handoff id is invalid")
        digest = handoff_id.removeprefix("executor-handoff:")
        return self._receipts_dir / f"{_RECEIPT_PREFIX}{digest}.json"

    def _ensure_receipts_dir(self) -> Path:
        invocations_dir = self._receipts_dir.parent
        if invocations_dir.is_symlink() or not invocations_dir.is_dir():
            raise InvocationCompletionReceiptError(
                "checkpoint store is not initialized: invocations/ is missing"
            )
        receipts_dir = self._receipts_dir
        if receipts_dir.is_symlink():
            raise InvocationCompletionReceiptError("receipts dir is a symlink")
        try:
            receipts_dir.mkdir(mode=0o700, exist_ok=True)
            os.chmod(receipts_dir, 0o700)
        except OSError as exc:
            raise InvocationCompletionReceiptError(
                "receipts dir is unavailable"
            ) from exc
        if not receipts_dir.is_dir() or receipts_dir.is_symlink():
            raise InvocationCompletionReceiptError("receipts dir is unavailable")
        return receipts_dir

    def _ensure_claims_dir(self) -> Path:
        invocations_dir = self._claims_dir.parent
        if invocations_dir.is_symlink() or not invocations_dir.is_dir():
            raise InvocationCompletionReceiptError(
                "checkpoint store is not initialized: invocations/ is missing"
            )
        claims_dir = self._claims_dir
        if claims_dir.is_symlink():
            raise InvocationCompletionReceiptError("claims dir is a symlink")
        try:
            claims_dir.mkdir(mode=0o700, exist_ok=True)
            os.chmod(claims_dir, 0o700)
        except OSError as exc:
            raise InvocationCompletionReceiptError("claims dir is unavailable") from exc
        if not claims_dir.is_dir() or claims_dir.is_symlink():
            raise InvocationCompletionReceiptError("claims dir is unavailable")
        return claims_dir

    def _claim_path(self, handoff_id: str) -> Path:
        if type(handoff_id) is not str or _HANDOFF_RE.fullmatch(handoff_id) is None:
            raise InvocationCompletionReceiptError("handoff id is invalid")
        digest = handoff_id.removeprefix("executor-handoff:")
        return self._claims_dir / f"{_CLAIM_PREFIX}{digest}.json"

    def find_completed(self, handoff_id: str) -> dict[str, Any] | None:
        """Return the completed receipt for one handoff, or ``None``."""
        path = self._receipt_path(handoff_id)
        raw = _read_regular_store_entry(path, what="completion receipt")
        if raw is None:
            return None
        try:
            receipt = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise InvocationCompletionReceiptError(
                "completion receipt is malformed"
            ) from exc
        _validate_receipt_body(receipt)
        if receipt["handoff_id"] != handoff_id:
            raise InvocationCompletionReceiptError(
                "completion receipt handoff does not match its file"
            )
        return receipt

    def record_completed(self, receipt: dict[str, Any]) -> Path:
        """Persist one completed receipt atomically; idempotent on identical content."""
        _validate_receipt_body(receipt)
        receipts_dir = self._ensure_receipts_dir()
        final = self._receipt_path(receipt["handoff_id"])
        payload = (
            json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        temp_name = _write_temp_file(receipts_dir, payload)
        try:
            if _link_or_exists(temp_name, final):
                _read_back(final, receipt, what="completion receipt")
                return final
            try:
                existing = final.read_bytes()
            except OSError as exc:
                raise InvocationCompletionReceiptError(
                    "completion receipt is unreadable"
                ) from exc
            if existing == payload:
                _sync_parent_directory(final)
                return final
            raise InvocationCompletionReceiptError(
                "completion receipt already holds different content"
            ) from None
        finally:
            _discard_temp(temp_name)

    def find_claim(self, handoff_id: str) -> dict[str, Any] | None:
        """Return the execution claim for one handoff, or ``None``."""
        path = self._claim_path(handoff_id)
        raw = _read_regular_store_entry(path, what="execution claim")
        if raw is None:
            return None
        try:
            claim = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise InvocationCompletionReceiptError(
                "execution claim is malformed"
            ) from exc
        _validate_claim_body(claim)
        if claim["handoff_id"] != handoff_id:
            raise InvocationCompletionReceiptError(
                "execution claim handoff does not match its file"
            )
        return claim

    def claim(self, handoff_id: str, run_id: str) -> bool:
        """Atomically claim one handoff for this delivery's run id.

        Returns True when this call created the claim (this delivery owns
        it), False when another delivery's claim already exists. A claim
        file is never overwritten: replacing a stale claim is an explicit
        release-then-claim by the delivery that proved it stale.
        """
        claim_body = build_execution_claim(handoff_id=handoff_id, run_id=run_id)
        claims_dir = self._ensure_claims_dir()
        final = self._claim_path(handoff_id)
        payload = (
            json.dumps(claim_body, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        temp_name = _write_temp_file(claims_dir, payload)
        try:
            if _link_or_exists(temp_name, final):
                _read_back(final, claim_body, what="execution claim")
                return True
            # The file already exists: claiming is idempotent for the
            # owning run (a retry after a crash between link and return),
            # and a refusal for any other run.
            existing = self.find_claim(handoff_id)
            if existing is not None and existing.get("run_id") == run_id:
                _sync_parent_directory(final)
                return True
            return False
        finally:
            _discard_temp(temp_name)

    def release_claim(self, handoff_id: str, run_id: str) -> bool:
        """Remove the claim only when it still carries this delivery's run id.

        Returns True when a claim was removed, False when there was no
        claim or it belongs to another delivery (never removed). A missing
        claim is not an error: release is idempotent.
        """
        if type(run_id) is not str or _RUN_ID_RE.fullmatch(run_id) is None:
            raise InvocationCompletionReceiptError("run id is invalid")
        path = self._claim_path(handoff_id)
        if path.is_symlink():
            raise InvocationCompletionReceiptError("execution claim is a symlink")
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise InvocationCompletionReceiptError(
                "execution claim is unreadable"
            ) from exc
        try:
            claim = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise InvocationCompletionReceiptError(
                "execution claim is malformed"
            ) from exc
        _validate_claim_body(claim)
        if claim["handoff_id"] != handoff_id or claim["run_id"] != run_id:
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise InvocationCompletionReceiptError(
                "execution claim could not be released"
            ) from exc
        return True

    def wait_for_completed(
        self,
        handoff_id: str,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float = 0.05,
    ) -> dict[str, Any] | None:
        """Poll for a completed receipt until it appears or the deadline passes.

        Store errors propagate (a malformed or unreadable receipt fails
        closed); an absent receipt is ``None``, never an error.
        """
        if not isinstance(timeout_seconds, (int, float)) or isinstance(
            timeout_seconds, bool
        ):
            raise TypeError("timeout_seconds must be a number")
        if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
            raise ValueError("timeout_seconds must be finite and >= 0")
        deadline = time.monotonic() + float(timeout_seconds)
        while True:
            found = self.find_completed(handoff_id)
            if found is not None:
                return found
            if time.monotonic() >= deadline:
                return None
            time.sleep(poll_interval_seconds)

    def verify_writable(self) -> None:
        """Fail fast when the receipts or claims directory cannot be written.

        Ensures both directories exist (created 0700) and probe-writes a
        temp file in each. This is the startup probe the production
        bootstrap runs before any execution: a permanently broken store
        must fail binding, not silently run without dedup.
        """
        for directory in (self._ensure_receipts_dir(), self._ensure_claims_dir()):
            temp_name: str | None = None
            descriptor: int | None = None
            try:
                descriptor, temp_name = tempfile.mkstemp(
                    dir=os.fspath(directory), prefix=".tmp-probe-", suffix=".tmp"
                )
                os.write(descriptor, b"probe")
                os.fsync(descriptor)
            except OSError as exc:
                raise InvocationCompletionReceiptError(
                    "completion store is not writable"
                ) from exc
            finally:
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                if temp_name is not None:
                    try:
                        os.unlink(temp_name)
                    except OSError:
                        pass
