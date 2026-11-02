"""Library receipt verifier for the #3333 fixed HEAD pilot.

Truthful status (F2 correction): this is a library verifier with NO
proven non-test production caller. It is the code the Gate 2
controller's bounded receipt reference names
(``github-service-agent-governed-publication-path``), but that name
previously existed only as a label and a docstring: no non-test code
read ``invocations/receipts/`` back, and this module is NOT wired to
any production publication path. It verifies one durable bounded
receipt against DESCRIPTOR-DERIVED expectations supplied by the caller
-- the admitted handoff, expected SHA, request id, codespace, and
invocation/descriptor identity as the caller independently knows them.
A receipt's own claims are never their sole proof: every identity field
is compared, exact type and value, against the caller's expectation,
and the receipt file's SHA-256 digest is recomputed from the stored
bytes and compared against an expected digest when the caller supplies
one.

What this consumer does NOT prove, stated plainly: the receipt file
itself carries no workflow run id or publisher identity, so workflow /
run / publisher binding is a caller-side check (the caller binds the
artifact or publication record it fetched the receipt from to the run
it observed) and must be recorded by the caller, not claimed from the
receipt. Likewise the consumer verifies that the receipt's dispatch
evidence is internally consistent and matches the descriptor; it does
not re-execute the pilot and does not turn a driver-forged receipt
whose fields all match the descriptor into a detected forgery -- that
remains driver trust plus the controller's pre-dispatch claim and
sink checks. ``verified=False`` with a specific reason is the only
failure output; the consumer never projects success from a partial
match.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FIXED_ARGV = ["git", "rev-parse", "HEAD"]
OPERATION_ID = "codespace-implementation-pilot-v1"
RECEIPT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReceiptExpectation:
    """Descriptor-derived expectations, supplied by the caller, not the receipt."""

    repository: str
    issue_number: int
    handoff_id: str
    expected_sha: str
    request_id: str
    codespace_name: str
    admission_id: str
    invocation_id: str
    descriptor_id: str
    digest_or_none: str | None = None
    # Caller-side provenance, recorded but NOT provable from the receipt
    # body: the caller must have bound these to the artifact/publication
    # record it fetched. They are validated as non-empty strings only.
    workflow_run_id_or_none: str | None = None
    publisher_or_none: str | None = None


@dataclass(frozen=True, slots=True)
class ReceiptVerification:
    """Outcome of one consumer verification."""

    verified: bool
    reason: str
    digest: str
    receipt_path: str | None
    receipt: dict[str, Any] | None


def _mismatch(field: str) -> ReceiptVerification:
    return ReceiptVerification(
        verified=False,
        reason=f"receipt-verification-mismatch:{field}",
        digest="",
        receipt_path=None,
        receipt=None,
    )


def verify_receipt_mapping(
    receipt: dict[str, Any],
    expectation: ReceiptExpectation,
    *,
    digest: str = "",
    receipt_path: str | None = None,
) -> ReceiptVerification:
    """Verify a parsed receipt mapping against descriptor expectations."""
    if type(receipt) is not dict:
        return ReceiptVerification(
            verified=False,
            reason="receipt-verification-mismatch:receipt-not-a-mapping",
            digest=digest,
            receipt_path=receipt_path,
            receipt=None,
        )
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        return _mismatch("schema_version")
    if receipt.get("operation_id") != OPERATION_ID:
        return _mismatch("operation_id")
    expected_fields = {
        "repository": expectation.repository,
        "issue_number": expectation.issue_number,
        "handoff_id": expectation.handoff_id,
        "expected_sha": expectation.expected_sha,
        "request_id": expectation.request_id,
        "codespace_name": expectation.codespace_name,
        "admission_id": expectation.admission_id,
        "invocation_id": expectation.invocation_id,
        "descriptor_id": expectation.descriptor_id,
    }
    for field, value in expected_fields.items():
        actual = receipt.get(field)
        if type(actual) is not type(value) or actual != value:
            return _mismatch(field)
    if receipt.get("status") != "completed":
        return _mismatch("status")
    reason_codes = receipt.get("reason_codes")
    if (
        type(reason_codes) is not list
        or not reason_codes
        or any(type(r) is not str or not r for r in reason_codes)
        or "fixed-head-probe-passed" not in reason_codes
    ):
        return _mismatch("reason_codes")
    if type(receipt.get("exit_status")) is not int or receipt.get("exit_status") != 0:
        return _mismatch("exit_status")
    stdout = receipt.get("stdout_tail")
    if type(stdout) is not str or stdout.strip() != expectation.expected_sha:
        return _mismatch("stdout_tail")
    if receipt.get("stdout_truncated") is not False:
        return _mismatch("stdout_truncated")
    if receipt.get("stderr_truncated") is not False:
        return _mismatch("stderr_truncated")
    if receipt.get("argv") != FIXED_ARGV:
        return _mismatch("argv")
    if expectation.digest_or_none is not None and digest != expectation.digest_or_none:
        return ReceiptVerification(
            verified=False,
            reason="receipt-verification-mismatch:digest",
            digest=digest,
            receipt_path=receipt_path,
            receipt=receipt,
        )
    for field in ("workflow_run_id_or_none", "publisher_or_none"):
        value = getattr(expectation, field)
        if value is not None and (type(value) is not str or not value):
            return _mismatch(field)
    return ReceiptVerification(
        verified=True,
        reason="receipt-verified",
        digest=digest,
        receipt_path=receipt_path,
        receipt=receipt,
    )


def verify_receipt_file(
    path: str | Path, expectation: ReceiptExpectation
) -> ReceiptVerification:
    """Read a durable receipt file back and verify it.

    The digest is the SHA-256 of the exact stored bytes, so a stale or
    altered receipt (different bytes, same claims) fails the digest
    comparison when the caller supplies the expected digest. An
    unreadable, malformed, or non-mapping file verifies as False --
    never as success -- with a specific reason.
    """
    file_path = Path(path)
    try:
        raw = file_path.read_bytes()
    except OSError:
        return ReceiptVerification(
            verified=False,
            reason="receipt-verification-mismatch:receipt-unreadable",
            digest="",
            receipt_path=str(file_path),
            receipt=None,
        )
    digest = hashlib.sha256(raw).hexdigest()
    try:
        receipt = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return ReceiptVerification(
            verified=False,
            reason="receipt-verification-mismatch:receipt-malformed",
            digest=digest,
            receipt_path=str(file_path),
            receipt=None,
        )
    result = verify_receipt_mapping(
        receipt, expectation, digest=digest, receipt_path=str(file_path)
    )
    if not result.verified:
        # Field mismatches carry no digest/path from the helper; always
        # report the recomputed digest and the file path on failure.
        return ReceiptVerification(
            verified=False,
            reason=result.reason,
            digest=digest,
            receipt_path=str(file_path),
            receipt=result.receipt,
        )
    return result
