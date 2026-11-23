"""Secret-free admission, then one separately authorized write/readback."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

# Only known developer-authored admission reasons may reach public receipts.
_ADMISSION_REASONS = frozenset({
    "event-byte-bound-exceeded", "event-invalid-structure",
    "event-invalid-json", "event-invalid-encoding",
    "untrusted-execution-context", "created-comment-required",
    "repository-mismatch", "ordinary-issue-request-required",
    "explicit-owner-request-required", "comment-identity-required",
    "edited-comment-refused", "finite-request-required",
    "update-binding-not-applicable", "exact-update-binding-required",
    "reviewed-target-lesson-mismatch", "canonical-owner-request-unavailable",
    "canonical-comment-target-mismatch", "canonical-owner-request-changed",
})


def _bounded_reason(exc: WriteBlocked) -> str:
    code = exc.args[0] if len(exc.args) == 1 else None
    return code if type(code) is str and code in _ADMISSION_REASONS else "bounded-request-unavailable"


def _save_receipt(path: Path, value: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def _unverified(reason: str) -> dict:
    return {
        "status": "unverified", "reason_code": reason,
        "independent_readback_verified": False,
        "persisted_state_verified": False, "write_causality_established": False,
        "read_performed": False, "verification_write_performed": False,
        "publication_authorized": False, "activation_authorized": False,
    }

from .admission import MAX_EVENT_BYTES, WriteBlocked, admit, verify_current_request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("admit", "execute"), required=True)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = {"request_id": None, "status": "blocked", "reason_code": "admission-failed",
              "write_attempts": 0, "readback_verified": False}
    admitted_request_id = None
    phase = "transport"
    try:
        with args.event.open("rb") as source:
            raw = source.read(MAX_EVENT_BYTES + 1)
        if len(raw) > MAX_EVENT_BYTES:
            raise WriteBlocked("event-byte-bound-exceeded")
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WriteBlocked("event-invalid-json") from exc
        except UnicodeDecodeError as exc:
            raise WriteBlocked("event-invalid-encoding") from exc
        if type(event) is not dict:
            raise WriteBlocked("event-invalid-structure")
        phase = "admission"
        context = dict(event_name=os.environ.get("GITHUB_EVENT_NAME", ""),
                       ref=os.environ.get("GITHUB_REF", ""),
                       workflow_ref=os.environ.get("GITHUB_WORKFLOW_REF", ""),
                       run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", ""))
        request = admit(event, **context)
        admitted_request_id = request.request_id
        result["request_id"] = request.request_id
        if args.phase == "admit":
            result.update(status="admitted", reason_code="explicit-bounded-owner-request",
                          comment_id=request.comment_id)
        else:
            phase = "current-request"
            verify_current_request(event, request, context=context)
            from .live import LiveLessonsClient
            from .writer import execute
            client = LiveLessonsClient(request.request_id)
            phase = "execution"
            candidate = execute(request, client)
            if type(candidate) is not dict:
                raise RuntimeError("invalid writer result")
            result = candidate
    except WriteBlocked as exc:
        result["reason_code"] = _bounded_reason(exc)
        if phase == "execution":
            result.update(status="uncertain", write_attempts=1, readback_verified=False)
        admitted_request_id = None
    except OSError:
        result["reason_code"] = "event-unreadable" if phase == "transport" else "bounded-request-unavailable"
        if phase == "execution":
            result.update(status="uncertain", write_attempts=1, readback_verified=False)
        admitted_request_id = None
    except Exception:
        result["reason_code"] = "bounded-request-unavailable"
        if phase == "execution":
            result.update(status="uncertain", write_attempts=1, readback_verified=False)
        admitted_request_id = None
    # This read-only second GET stays inside the SINGLE credential-bearing
    # execute step. A failure never retries the original mutation.
    verification = None
    if args.phase == "execute":
        from .verify_live_write import verify_persisted_write

        def live_client(request_id: str):
            from .live import LiveLessonsClient
            return LiveLessonsClient(request_id)

        if (result.get("status") in ("persisted", "unchanged")
                and admitted_request_id is not None
                and result.get("request_id") == admitted_request_id):
            try:
                verification = verify_persisted_write(
                    result, live_client, expected_request_id=admitted_request_id
                )
            except Exception:
                verification = _unverified("independent-verifier-unavailable")
        else:
            verification = _unverified(
                "writer-request-binding-mismatch"
                if result.get("status") in ("persisted", "unchanged")
                else "writer-did-not-confirm-persistence"
            )
    if verification is not None and not _save_receipt(args.output.with_name("verification.json"), verification):
        return 1
    if not _save_receipt(args.output, result):
        return 1
    if args.phase == "admit":
        return 0 if result["status"] == "admitted" else 1
    return 0 if (
        (result["status"] == "persisted" and verification["status"] == "verified-current-state")
        or (result["status"] == "unchanged" and verification["status"] == "no-new-write")
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
