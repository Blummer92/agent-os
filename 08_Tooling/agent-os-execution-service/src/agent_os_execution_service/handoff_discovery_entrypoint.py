"""Fixed read-only host entrypoint for Agent OS handoff discovery.

This entrypoint accepts only canonical repository + issue identity, binds the
checkpoint-store root from trusted host composition, delegates to the existing
#1242 discover_issue_handoff(...) implementation, and returns bounded JSON.

It performs no Scheduler dispatch, GitHub write, arbitrary command execution,
handoff generation, store mutation, or execution authorization.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from scripts.agent_os_execution_checkpoint.handoff_discovery import discover_issue_handoff

DEFAULT_STORE_ROOT = "/var/lib/agent-os/checkpoints"
ALLOWED_REPOSITORY = "Blummer92/agent-os"


def _store_root() -> Path:
    # Host composition may set the canonical root. It is never accepted via argv.
    value = os.environ.get("AGENT_OS_CHECKPOINT_STORE_ROOT", DEFAULT_STORE_ROOT)
    if not value.startswith("/"):
        raise RuntimeError("checkpoint store root must be absolute")
    return Path(value)


def run_discovery(*, repository: str, issue_number: int) -> dict[str, object]:
    if repository != ALLOWED_REPOSITORY:
        raise ValueError("repository is not the approved Agent OS repository")
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("issue number must be a positive integer")

    result = discover_issue_handoff(
        _store_root(),
        repository=repository,
        issue_number=issue_number,
    )
    payload = {
        "status": result.status.value,
        "reason_codes": [item.value for item in result.reason_codes],
        "repository": result.repository,
        "issue_number": result.issue_number,
        "matching_descriptor_count": result.matching_descriptor_count,
        "handoff_id": result.handoff_id,
        "result_id": result.result_id,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "side_effects_performed": False,
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue-number", required=True, type=int)
    args = parser.parse_args(argv)

    payload = run_discovery(
        repository=args.repository,
        issue_number=args.issue_number,
    )
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
