#!/usr/bin/env python3
"""Compatibility entrypoint that binds issue closure to canonical lifecycle admission.

The release state machine remains in ``agent_os_release_run_core``. This wrapper
preserves that public surface while deriving ``issue_closure_authorized`` only
from the existing content-bound lifecycle mutation authorization + snapshot.
A legacy caller-supplied boolean is deliberately ignored as authority.
"""
from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path
from typing import Any

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from agent_os_release_run_core import *  # noqa: F401,F403
from agent_os_release_run_core import evaluate_release_run as _evaluate_release_run_core
from agent_os_issue_acceptance.lifecycle_mutation_guard import (
    AdmissionStatus,
    LifecycleMutationAuthorization,
    LifecycleStateSnapshot,
    evaluate_lifecycle_mutation,
)


def _construct_exact(cls: type, raw: Any, name: str):
    if not isinstance(raw, dict):
        raise TypeError(f"{name} must be object")
    allowed = {item.name for item in fields(cls)}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"{name} contains unsupported fields")
    return cls(**raw)


def _closure_admitted(evidence: dict[str, Any]) -> bool:
    raw = evidence.get("issue_closure_lifecycle")
    if raw is None:
        return False
    if not isinstance(raw, dict):
        raise TypeError("issue_closure_lifecycle must be object or null")
    if set(raw) != {"authorization", "snapshot"}:
        raise ValueError(
            "issue_closure_lifecycle must contain exactly authorization and snapshot"
        )

    authorization = _construct_exact(
        LifecycleMutationAuthorization,
        raw["authorization"],
        "lifecycle authorization",
    )
    snapshot = _construct_exact(
        LifecycleStateSnapshot,
        raw["snapshot"],
        "lifecycle snapshot",
    )

    if snapshot.repository != evidence.get("repository"):
        return False
    if snapshot.issue_number != evidence.get("issue_number"):
        return False
    if snapshot.pull_request_number != evidence.get("pull_request_number"):
        return False
    if snapshot.source_head != evidence.get("observed_head_sha"):
        return False
    if snapshot.issue_state != evidence.get("issue_state"):
        return False

    admission = evaluate_lifecycle_mutation(
        authorization,
        snapshot,
        "close-issue",
    )
    return admission.status is AdmissionStatus.ADMITTED and admission.admitted


def evaluate_release_run(evidence: dict[str, Any]):
    """Evaluate release evidence with closure authority derived canonically."""
    if not isinstance(evidence, dict):
        raise TypeError("release evidence must be object")
    canonical = dict(evidence)
    canonical["issue_closure_authorized"] = _closure_admitted(evidence)
    return _evaluate_release_run_core(canonical)


def main() -> int:
    import argparse
    import json
    from dataclasses import asdict

    parser = argparse.ArgumentParser(
        description="Evaluate bounded Agent OS release-run evidence"
    )
    parser.add_argument("evidence", help="Path to JSON evidence file")
    args = parser.parse_args()
    with open(args.evidence, encoding="utf-8") as handle:
        evidence = json.load(handle)
    print(
        json.dumps(
            asdict(evaluate_release_run(evidence)),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
