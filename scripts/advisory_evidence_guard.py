"""Fail an advisory CI job visibly when scanner evidence is not trustworthy (#3759/#3761).

The jscpd and pyan3 producers deliberately exit 0 and record ``scanner-error`` in
their JSON, and the upload step ignores missing files, so a broken scanner used to
leave a green job. This guard only *classifies* the producer's evidence file. It
grants no authority, changes no requiredness, and never gates the aggregate.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MAX_EVIDENCE_BYTES = 8_000_000
_SHA = re.compile(r"^[0-9a-f]{40}$")
_SCHEMAS = {"jscpd": "agent-os-jscpd-advisory/1", "pyan3": "agent-os-pyan3-advisory/1"}
PASSING = frozenset({"ok", "ok-zero-findings"})


def classify(kind: str, path: Path, expected_sha: str) -> tuple[str, str]:
    """Return ``(state, detail)``; only ``ok`` and ``ok-zero-findings`` may pass."""
    if kind not in _SCHEMAS:
        raise ValueError(f"unknown advisory kind: {kind}")
    if not _SHA.fullmatch(expected_sha):
        return "invalid-evidence", "expected head SHA is not a 40-hex commit"
    if not path.is_file():
        return "artifact-missing", f"{path} was not produced"
    try:
        if path.stat().st_size > MAX_EVIDENCE_BYTES:
            return "invalid-evidence", "evidence exceeds the size cap"
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "invalid-evidence", "evidence is unreadable or not JSON"
    if not isinstance(data, dict) or data.get("schema") != _SCHEMAS[kind] or data.get("tool") != kind:
        return "invalid-evidence", "schema or tool does not match the producer contract"
    if data.get("head_sha") != expected_sha:
        return "stale-sha", "evidence head_sha does not match the pull request head"
    status = data.get("status")
    if status == "scanner-error":
        return "scanner-error", str(data.get("detail") or "producer reported scanner-error")[:200]
    if status != "ok":
        return "invalid-evidence", "status is not a recognized value"
    count = data.get("candidate_count")
    if type(count) is not int or count < 0:
        return "invalid-evidence", "candidate_count is not a non-negative integer"
    return ("ok-zero-findings" if count == 0 else "ok"), f"{count} advisory candidate(s)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=sorted(_SCHEMAS))
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args(argv)
    state, detail = classify(args.kind, args.file, args.sha)
    print(json.dumps({"kind": args.kind, "state": state, "detail": detail, "head_sha": args.sha}, sort_keys=True))
    if state in PASSING:
        return 0
    print(f"::error::{args.kind} advisory evidence is {state}: {detail}. Advisory only; no merge authority is changed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
