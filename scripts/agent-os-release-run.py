#!/usr/bin/env python3
"""Deterministic, offline release-run state evaluator for Agent OS."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_NAME = "agent-os-release-run"
SCHEMA_VERSION = "1.0.0"
CLASSIFICATIONS = {"READY_FOR_MERGE_AUTHORIZATION", "NEEDS_FIX", "BLOCKED"}
BAD_CHECKS = {"missing", "pending", "skipped", "cancelled", "timed_out", "failed", "failure"}


@dataclass
class ReleaseRunState:
    schema_name: str = SCHEMA_NAME
    schema_version: str = SCHEMA_VERSION
    repository: str = ""
    pull_request_number: int = 0
    issue_number: int = 0
    expected_head_sha: str = ""
    observed_head_sha: str = ""
    phase: str = "preflight"
    classification: str = "BLOCKED"
    pr_state: str = "open"
    issue_state: str = "open"
    changed_files: list[str] = field(default_factory=list)
    required_checks: dict[str, str] = field(default_factory=dict)
    review_thread_summary: dict[str, int] = field(default_factory=dict)
    ready_for_review_authorized: bool = False
    merge_authorized: bool = False
    issue_closure_authorized: bool = False
    next_action: str = "stop"
    blockers: list[str] = field(default_factory=list)
    side_effects_performed: list[str] = field(default_factory=list)


def evaluate_release_run(evidence: dict[str, Any]) -> ReleaseRunState:
    state = ReleaseRunState(
        repository=str(evidence.get("repository", "")),
        pull_request_number=int(evidence.get("pull_request_number", 0)),
        issue_number=int(evidence.get("issue_number", 0)),
        expected_head_sha=str(evidence.get("expected_head_sha", "")),
        observed_head_sha=str(evidence.get("observed_head_sha", "")),
        pr_state=str(evidence.get("pr_state", "open")),
        issue_state=str(evidence.get("issue_state", "open")),
        changed_files=sorted(set(evidence.get("changed_files", []))),
        required_checks=dict(sorted(evidence.get("required_checks", {}).items())),
        review_thread_summary=dict(sorted(evidence.get("review_thread_summary", {}).items())),
        ready_for_review_authorized=bool(evidence.get("ready_for_review_authorized", False)),
        merge_authorized=bool(evidence.get("merge_authorized", False)),
        issue_closure_authorized=bool(evidence.get("issue_closure_authorized", False)),
        side_effects_performed=list(evidence.get("side_effects_performed", [])),
    )
    allowed = set(evidence.get("allowed_changed_files", []))
    if not state.repository or not state.pull_request_number or not state.issue_number:
        state.blockers.append("missing release-run identity")
    if state.pr_state not in {"open", "merged"}:
        state.blockers.append(f"unsupported PR state: {state.pr_state}")
    if state.expected_head_sha != state.observed_head_sha:
        state.blockers.append("exact-head drift")
    if allowed and not set(state.changed_files).issubset(allowed):
        state.blockers.append("changed-file scope drift")
    bad = [name for name, result in state.required_checks.items() if str(result).lower() in BAD_CHECKS]
    if bad:
        state.blockers.append("required checks not successful: " + ", ".join(sorted(bad)))
    if evidence.get("prior_head_only_green", False):
        state.blockers.append("prior-head checks cannot satisfy current head")
    if evidence.get("requested_changes", False):
        state.blockers.append("requested-changes review is unresolved")
    if int(state.review_thread_summary.get("blocking_unresolved", 0)) > 0:
        state.blockers.append("blocking review conversation is unresolved")
    if state.blockers:
        state.phase = "release-review"
        state.classification = "NEEDS_FIX" if evidence.get("fixable", False) else "BLOCKED"
        state.next_action = "repair-or-resolve-blockers"
        return state

    if state.pr_state == "merged":
        if evidence.get("merge_commit_verified", False) is not True or evidence.get("main_verified", False) is not True:
            state.phase = "post-merge-verification"
            state.classification = "BLOCKED"
            state.blockers.append("post-merge verification incomplete")
            state.next_action = "verify-merge-and-main"
        elif not state.issue_closure_authorized:
            state.phase = "issue-closure-authorization-pause"
            state.classification = "BLOCKED"
            state.next_action = "request-issue-closure-authorization"
        elif "completion-comment" not in state.side_effects_performed:
            state.phase = "issue-closure"
            state.classification = "BLOCKED"
            state.next_action = "post-completion-comment-before-closure"
        else:
            state.phase = "issue-closure"
            state.classification = "READY_FOR_MERGE_AUTHORIZATION"
            state.next_action = "close-issue"
        return state

    if not state.ready_for_review_authorized:
        state.phase = "ready-for-review"
        state.classification = "BLOCKED"
        state.next_action = "request-ready-for-review-authorization"
    elif not state.merge_authorized:
        state.phase = "merge-authorization-pause"
        state.classification = "READY_FOR_MERGE_AUTHORIZATION"
        state.next_action = "request-merge-authorization"
    else:
        state.phase = "merge"
        state.classification = "READY_FOR_MERGE_AUTHORIZATION"
        state.next_action = "merge-at-expected-head-with-approved-method"
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate bounded Agent OS release-run evidence")
    parser.add_argument("evidence", help="Path to JSON evidence file")
    args = parser.parse_args()
    with open(args.evidence, encoding="utf-8") as handle:
        evidence = json.load(handle)
    print(json.dumps(asdict(evaluate_release_run(evidence)), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
