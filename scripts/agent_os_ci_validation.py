from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXECUTION_SERVICE_SRC = ROOT / "08_Tooling/agent-os-execution-service/src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EXECUTION_SERVICE_SRC))

from agent_os_execution_service.command_planning import _COMMAND_REGISTRY
from scripts.agent_os_remote_validation import ValidationPlan, validate_validation_plan

_PICTURE_PERFECT_CHECK = (
    "cd 08_Tooling/instructional-materials-coach/picture-perfect-coach && npm run check"
)
_PICTURE_PERFECT_DIR = (
    ROOT / "08_Tooling/instructional-materials-coach/picture-perfect-coach"
)


def _decode_plan(encoded: str) -> ValidationPlan:
    try:
        raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("validation plan payload is malformed") from exc
    if type(payload) is not dict:
        raise TypeError("validation plan payload must be an object")
    expected = {
        "schema_name",
        "schema_version",
        "selector_version",
        "repository",
        "pull_request",
        "base_sha",
        "head_sha",
        "profile",
        "commands",
        "command_set_digest",
        "reason_codes",
        "remote_build_required",
        "execution_authorized",
        "side_effects_performed",
    }
    if set(payload) != expected:
        raise ValueError("validation plan payload fields do not match canonical schema")
    if payload["execution_authorized"] is not False or payload["side_effects_performed"] is not False:
        raise ValueError("validation plan authority fields must remain false")
    if type(payload["commands"]) is not list or type(payload["reason_codes"]) is not list:
        raise TypeError("validation plan commands and reasons must be lists")
    plan = ValidationPlan(
        selector_version=payload["selector_version"],
        repository=payload["repository"],
        pull_request=payload["pull_request"],
        base_sha=payload["base_sha"],
        head_sha=payload["head_sha"],
        profile=payload["profile"],
        commands=tuple(payload["commands"]),
        command_set_digest=payload["command_set_digest"],
        reason_codes=tuple(payload["reason_codes"]),
        remote_build_required=payload["remote_build_required"],
    )
    reasons = validate_validation_plan(plan)
    if reasons:
        raise ValueError("validation plan failed canonical validation: " + ",".join(reasons))
    return plan


def _current_head() -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout.strip()


def _resolve_command(command: str) -> tuple[tuple[str, ...], Path]:
    argv = _COMMAND_REGISTRY.get(command)
    if argv is not None:
        return argv, ROOT
    if command == _PICTURE_PERFECT_CHECK:
        return ("npm", "run", "check"), _PICTURE_PERFECT_DIR
    raise ValueError(f"validation command is not in the bounded CI executor: {command}")


def execute_focused(plan: ValidationPlan, *, expected_head_sha: str) -> None:
    if plan.profile != "focused":
        raise ValueError("bounded CI executor accepts focused plans only")
    if plan.head_sha != expected_head_sha:
        raise ValueError("validation plan head does not match expected PR head")
    checked_out = _current_head()
    if checked_out != expected_head_sha:
        raise ValueError(
            f"checked-out SHA {checked_out} does not match expected PR head {expected_head_sha}"
        )
    for command in plan.commands:
        argv, cwd = _resolve_command(command)
        subprocess.run(argv, cwd=cwd, check=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-base64", required=True)
    parser.add_argument("--expected-head-sha", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    plan = _decode_plan(args.plan_base64)
    execute_focused(plan, expected_head_sha=args.expected_head_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
