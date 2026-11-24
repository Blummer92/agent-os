"""Validate one fresh pytest JUnit report without trusting pytest's exit alone."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from agent_os_ci_junit_diff import TEST_COMPLETENESS_SCHEMA, junit_outcomes


def _suite_receipt(path: Path, suite: str, data: bytes, outcome: dict) -> bool:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        return False
    count = receipt.get("expected_count")
    missing = receipt.get("missing_count")
    mandatory = receipt.get("skipped_mandatory")
    error = receipt.get("error")
    verdict = receipt.get("verdict")
    if type(count) is not int or count < 1 or type(missing) is not int or missing < 0:
        return False
    if not isinstance(mandatory, list) or any(not isinstance(node, str) for node in mandatory):
        return False
    if verdict == "COMPLETE":
        if "error" not in receipt or error is not None or missing or mandatory or count > outcome["tests"]:
            return False
    elif verdict == "INCOMPLETE":
        # Execution can succeed while independent completeness fails. The
        # separate receipt row and aggregate must still report that failure.
        if not isinstance(error, str) or not error or not (missing or mandatory):
            return False
    else:
        return False
    receipt_outcome = receipt.get("outcome")
    if not isinstance(receipt_outcome, dict) or any(
        type(receipt_outcome.get(key)) is not int for key in ("tests", "failures", "errors", "skipped")
    ):
        return False
    return (
        receipt.get("schema") == TEST_COMPLETENESS_SCHEMA
        and receipt.get("suite_name") == suite
        and type(receipt.get("executed_count")) is int
        and receipt["executed_count"] == outcome["tests"]
        and receipt.get("skip_allowlist_stale") == []
        and receipt.get("junit_sha256") == hashlib.sha256(data).hexdigest()
        and type(receipt.get("reference_returncode")) is int
        and receipt["reference_returncode"] == 0
        and type(receipt.get("reference_noconftest_returncode")) is int
        and receipt["reference_noconftest_returncode"] == 0
        and receipt_outcome == outcome
    )


def main() -> int:
    options = sys.argv[2:]
    focused = options == ["--require-executed"]
    receipt_check = len(options) == 3 and options[0] == "--suite-receipt"
    if len(sys.argv) < 2 or (options and not (focused or receipt_check)):
        return 2
    try:
        data = Path(sys.argv[1]).read_bytes()
        outcome = junit_outcomes(data)
        if outcome["failures"] or outcome["errors"]:
            return 1
        if not outcome["tests"] or ((focused or receipt_check) and outcome["tests"] <= outcome["skipped"]):
            return 2
        if receipt_check and not _suite_receipt(Path(options[1]), options[2], data, outcome):
            return 2
    except (OSError, ValueError, TypeError):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
