"""Fail-closed developer-validation gate for governed GitHub-to-GCE evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEV_VALIDATION_REASON = "accepted-dev-validation-envelope"
_ALLOWED_STATUSES = frozenset({"success", "failure", "timeout", "needs-decision"})
_SHA40 = re.compile(r"^[0-9a-f]{40}$", re.ASCII)


@dataclass(frozen=True, slots=True)
class DevValidationGateDecision:
    applies: bool
    passed: bool
    status: str
    reason: str
    tested_sha: str | None = None
    validation_id: str | None = None
    exit_code: int | None = None
    cleanup_complete: bool | None = None


def _failure(
    reason: str,
    *,
    status: str = "needs-decision",
    tested_sha: object = None,
    validation_id: object = None,
    exit_code: object = None,
    cleanup_complete: object = None,
) -> DevValidationGateDecision:
    return DevValidationGateDecision(
        applies=True,
        passed=False,
        status=status,
        reason=reason,
        tested_sha=tested_sha if type(tested_sha) is str else None,
        validation_id=validation_id if type(validation_id) is str else None,
        exit_code=exit_code if type(exit_code) is int and type(exit_code) is not bool else None,
        cleanup_complete=cleanup_complete if type(cleanup_complete) is bool else None,
    )


def evaluate_dev_validation_gate(
    transport: Mapping[str, object],
    result: Mapping[str, object] | None,
) -> DevValidationGateDecision:
    """Return whether canonical developer-validation evidence satisfies the gate.

    Non-developer-validation ingress is intentionally not affected. For an
    accepted developer-validation envelope, only structurally valid exact-identity
    evidence with ``status == success``, ``exit_code == 0``, and completed cleanup
    can pass. Everything else fails closed without granting any authority.
    """

    if type(transport) is not dict:
        return _failure("transport-evidence-malformed")
    if transport.get("reason") != DEV_VALIDATION_REASON:
        return DevValidationGateDecision(
            applies=False,
            passed=True,
            status="not-applicable",
            reason="not-dev-validation",
        )
    if transport.get("status") != "accepted":
        return _failure("dev-validation-transport-not-accepted")
    if type(result) is not dict:
        return _failure("dev-validation-result-missing-or-malformed")

    evidence = result.get("dev_validation")
    if type(evidence) is not dict:
        return _failure("dev-validation-result-missing-or-malformed")

    status = evidence.get("status")
    tested_sha = evidence.get("tested_sha")
    validation_id = evidence.get("validation_id")
    exit_code = evidence.get("exit_code")
    cleanup_complete = evidence.get("cleanup_complete")
    reason_codes = evidence.get("reason_codes")

    if status not in _ALLOWED_STATUSES:
        return _failure(
            "dev-validation-status-invalid",
            tested_sha=tested_sha,
            validation_id=validation_id,
            exit_code=exit_code,
            cleanup_complete=cleanup_complete,
        )
    if (
        type(reason_codes) is not list
        or not reason_codes
        or any(type(item) is not str or not item for item in reason_codes)
    ):
        return _failure(
            "dev-validation-reason-codes-invalid",
            status=status,
            tested_sha=tested_sha,
            validation_id=validation_id,
            exit_code=exit_code,
            cleanup_complete=cleanup_complete,
        )

    expected_sha = transport.get("dev_validation_sha_or_none")
    expected_id = transport.get("dev_validation_id_or_none")
    expected_branch = transport.get("dev_validation_branch_or_none")
    if (
        type(expected_sha) is not str
        or _SHA40.fullmatch(expected_sha) is None
        or type(expected_id) is not str
        or not expected_id
        or type(expected_branch) is not str
        or not expected_branch
        or evidence.get("tested_sha") != expected_sha
        or evidence.get("validation_id") != expected_id
        or evidence.get("branch") != expected_branch
    ):
        return _failure(
            "dev-validation-identity-mismatch",
            status=status,
            tested_sha=tested_sha,
            validation_id=validation_id,
            exit_code=exit_code,
            cleanup_complete=cleanup_complete,
        )

    if status != "success":
        return _failure(
            "dev-validation-not-success",
            status=status,
            tested_sha=tested_sha,
            validation_id=validation_id,
            exit_code=exit_code,
            cleanup_complete=cleanup_complete,
        )
    if exit_code != 0:
        return _failure(
            "dev-validation-success-exit-code-invalid",
            status=status,
            tested_sha=tested_sha,
            validation_id=validation_id,
            exit_code=exit_code,
            cleanup_complete=cleanup_complete,
        )
    if cleanup_complete is not True:
        return _failure(
            "dev-validation-success-cleanup-incomplete",
            status=status,
            tested_sha=tested_sha,
            validation_id=validation_id,
            exit_code=exit_code,
            cleanup_complete=cleanup_complete,
        )

    return DevValidationGateDecision(
        applies=True,
        passed=True,
        status="success",
        reason="validation-passed",
        tested_sha=tested_sha,
        validation_id=validation_id,
        exit_code=0,
        cleanup_complete=True,
    )


def _load_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        raise ValueError("evidence must be a JSON object")
    return payload


def _format(decision: DevValidationGateDecision) -> str:
    return (
        "Developer validation gate: "
        f"status={decision.status} "
        f"reason={decision.reason} "
        f"tested_sha={decision.tested_sha or 'unavailable'} "
        f"validation_id={decision.validation_id or 'unavailable'} "
        f"exit_code={decision.exit_code if decision.exit_code is not None else 'unavailable'} "
        f"cleanup_complete={decision.cleanup_complete if decision.cleanup_complete is not None else 'unavailable'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        transport = _load_object(args.transport)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Developer validation gate: transport evidence unavailable ({type(exc).__name__})", file=sys.stderr)
        return 1

    if transport.get("reason") != DEV_VALIDATION_REASON:
        return 0

    try:
        result = _load_object(args.result)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Developer validation gate: result evidence unavailable ({type(exc).__name__})", file=sys.stderr)
        return 1

    decision = evaluate_dev_validation_gate(transport, result)
    print(_format(decision))
    return 0 if decision.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
