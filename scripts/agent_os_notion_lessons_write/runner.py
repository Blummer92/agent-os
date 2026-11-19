"""Secret-free admission, then one separately authorized write/readback."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

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
    try:
        with args.event.open("rb") as source:
            raw = source.read(MAX_EVENT_BYTES + 1)
        if len(raw) > MAX_EVENT_BYTES:
            raise WriteBlocked("event-byte-bound-exceeded")
        event = json.loads(raw)
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
            verify_current_request(event, request, context=context)
            from .live import LiveLessonsClient
            from .writer import execute
            result = execute(request, LiveLessonsClient(request.request_id))
    except WriteBlocked as exc:
        result["reason_code"] = str(exc)
    except Exception:
        result["reason_code"] = "bounded-request-unavailable"
    # This read-only second GET stays inside the SINGLE credential-bearing
    # execute step. A failure never retries the original mutation.
    verification = None
    if args.phase == "execute":
        from .verify_live_write import verify_persisted_write

        def live_client(request_id: str):
            from .live import LiveLessonsClient
            return LiveLessonsClient(request_id)

        try:
            verification = verify_persisted_write(
                result, live_client, expected_request_id=admitted_request_id
            )
        except Exception:
            verification = {
                "status": "unverified", "reason_code": "independent-verifier-unavailable",
                "independent_readback_verified": False,
                "persisted_state_verified": False,
                "write_causality_established": False,
                "read_performed": False, "verification_write_performed": False,
                "publication_authorized": False, "activation_authorized": False,
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if verification is not None:
        args.output.with_name("verification.json").write_text(
            json.dumps(verification, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
    if args.phase == "admit":
        return 0 if result["status"] == "admitted" else 1
    return 0 if (
        (result["status"] == "persisted" and verification["status"] == "verified-current-state")
        or (result["status"] == "unchanged" and verification["status"] == "no-new-write")
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
