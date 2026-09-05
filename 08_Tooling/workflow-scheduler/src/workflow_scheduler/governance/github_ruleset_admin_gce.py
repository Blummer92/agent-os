"""Finite GCE host caller for the separately authorized #1883 ruleset mutation.

This module is intentionally narrower than the normal governed-resume path.  It
accepts no repository, ruleset, action, URL, HTTP method, token, command, retry,
or fallback from the caller.  The only caller-supplied value is the fresh
content-bound pre-state digest; every other mutation field is fixed by the
existing GH-ADMIN1 adapter (#1893).
"""
from __future__ import annotations

import argparse
import json
import re
from typing import Sequence

from workflow_scheduler.adapters.github_ruleset_admin_adapter import (
    AUTHORIZATION_ISSUE,
    REPOSITORY,
    RULESET_ID,
    GitHubRulesetAdminAdapter,
)
from workflow_scheduler.models import Task

_PRESTATE_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
ACTION = "apply_1883_required_validation_gate"


def build_task(expected_prestate_sha256: str) -> Task:
    if type(expected_prestate_sha256) is not str or _PRESTATE_RE.fullmatch(expected_prestate_sha256) is None:
        raise ValueError("expected pre-state must be 64 lowercase hex characters")
    return Task(
        id="ruleset-admin-1883",
        workflow_id="gh-admin1-1883",
        type="github_ruleset_admin",
        owner="GitHub Service Agent",
        action=ACTION,
        idempotency_key="gh-admin1-1883",
        payload={
            "action": ACTION,
            "repository_full_name": REPOSITORY,
            "ruleset_id": RULESET_ID,
            "authorization_issue": AUTHORIZATION_ISSUE,
            "expected_prestate_sha256": expected_prestate_sha256,
        },
    )


def execute(expected_prestate_sha256: str, *, adapter: GitHubRulesetAdminAdapter | None = None) -> dict[str, object]:
    task = build_task(expected_prestate_sha256)
    result = (adapter or GitHubRulesetAdminAdapter()).execute(task)
    if not isinstance(result, dict):
        raise RuntimeError("ruleset adapter result must be an object")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-prestate-sha256", required=True)
    args = parser.parse_args(argv)
    result = execute(args.expected_prestate_sha256)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("status") == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
