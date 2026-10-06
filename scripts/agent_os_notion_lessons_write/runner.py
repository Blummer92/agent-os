"""Secret-free admission, then one separately authorized write/readback."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .admission import MAX_EVENT_BYTES, WriteBlocked, admit
from .catalog import REQUEST_ID


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("admit", "execute", "canary-admit", "canary-execute"), required=True)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = {"request_id": REQUEST_ID, "status": "blocked", "reason_code": "admission-failed",
              "write_attempts": 0, "readback_verified": False}
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
        canary = args.phase.startswith("canary-")
        if canary:
            from .canary import admit_canary
            request = admit_canary(event, **context, run_id=os.environ.get("GITHUB_RUN_ID", ""))
        else:
            request = admit(event, **context)
        if args.phase in {"admit", "canary-admit"}:
            result.update(status="admitted", reason_code="explicit-bounded-owner-request",
                          comment_id=request.comment_id)
        else:
            if not canary:
                from .currentness import verify_current_request
                verify_current_request(event, request, context=context)
            from .live import LiveLessonsClient
            from .writer import execute
            if canary:
                from .canary import execute_canary
                result = execute_canary(request, LiveLessonsClient())
            else:
                result = execute(request, LiveLessonsClient())
    except WriteBlocked as exc:
        result["reason_code"] = str(exc)
    except Exception:
        result["reason_code"] = "bounded-request-unavailable"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] in {"admitted", "persisted", "unchanged"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
