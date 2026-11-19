"""Disposable-only: intentionally fail the fresh aggregate on this one Ready event."""
import json
import os
from pathlib import Path


def test_d07_disposable_ready_event_requires_fresh_red_aggregate():
    if os.getenv("GITHUB_ACTIONS") != "true" or not os.getenv("CI_JUNIT_RUN_ID"):
        return
    if os.getenv("GITHUB_REPOSITORY") != "Blummer92/agent-os":
        return
    if os.getenv("GITHUB_EVENT_NAME") != "pull_request":
        return
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    if event.get("action") != "ready_for_review":
        return
    pr = event["pull_request"]
    if pr["base"]["ref"] != "main" or pr["head"]["ref"] != "d07/canary-ready-revalidation-never-merge":
        return
    raise AssertionError(
        "D07 intentional Ready-only aggregate negative: "
        f"run={os.environ['CI_JUNIT_RUN_ID']}; "
        f"attempt={os.environ['CI_JUNIT_RUN_ATTEMPT']}; "
        f"checkout_head={os.environ['CI_JUNIT_HEAD_SHA']}; "
        f"workflow_sha={os.environ['GITHUB_WORKFLOW_SHA']}; "
        f"workflow_ref={os.environ['GITHUB_WORKFLOW_REF']}"
    )
