"""Ingress admission for the fixed Ready-for-Review admission trigger (#3446).

``/agent-os ready-admit <pr> <head-sha40> <body-sha256>`` admits only an exact
bounded selector. It never authorizes execution and is never routed to a
Codespaces/GCE transport (the GitHub-hosted consumer job owns it).
"""
from __future__ import annotations

import pytest

from workflow_scheduler.governance.codespaces_first_route import resolve_ingress_route
from workflow_scheduler.governance.github_issue_comment_ingress import admit_issue_comment_event

REPOSITORY = "Blummer92/agent-os"
ACTOR = "Blummer92"
HEAD = "a" * 40
BODY = "b" * 64
TRIGGER = f"/agent-os ready-admit 3481 {HEAD} {BODY}"


def event(body: str, *, actor: str = ACTOR, sender: str | None = None, repo: str = REPOSITORY,
          pull_request: bool = False) -> dict[str, object]:
    issue: dict[str, object] = {"number": 3446}
    if pull_request:
        issue["pull_request"] = {}
    return {
        "action": "created",
        "repository": {"full_name": repo},
        "issue": issue,
        "comment": {"id": 9001, "body": body, "user": {"login": actor}},
        "sender": {"login": sender or actor},
    }


def admit(payload: object, *, run_attempt: int = 1):
    return admit_issue_comment_event(payload, expected_repository=REPOSITORY, allowed_actor=ACTOR,
                                     run_attempt=run_attempt)


def test_accepts_exact_fixed_request_with_bound_identity() -> None:
    result = admit(event(TRIGGER))
    assert (result.status, result.reason) == ("accepted", "accepted-ready-admission-envelope")
    assert result.ready_admission_pr_number_or_none == 3481
    assert result.ready_admission_head_sha_or_none == HEAD
    assert result.ready_admission_body_sha256_or_none == BODY
    assert result.logical_trigger_id_or_none is not None
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False
    payload = result.to_dict()
    assert payload["ready_admission_pr_number_or_none"] == 3481


def test_trigger_id_is_deterministic_and_binds_head_and_body() -> None:
    first = admit(event(TRIGGER)).logical_trigger_id_or_none
    assert first == admit(event(TRIGGER)).logical_trigger_id_or_none
    other_head = admit(event(f"/agent-os ready-admit 3481 {'c' * 40} {BODY}")).logical_trigger_id_or_none
    other_body = admit(event(f"/agent-os ready-admit 3481 {HEAD} {'d' * 64}")).logical_trigger_id_or_none
    other_pr = admit(event(f"/agent-os ready-admit 3482 {HEAD} {BODY}")).logical_trigger_id_or_none
    assert len({first, other_head, other_body, other_pr}) == 4


@pytest.mark.parametrize(
    "body",
    [
        f"/agent-os ready-admit 0 {HEAD} {BODY}",
        f"/agent-os ready-admit 03481 {HEAD} {BODY}",
        f"/agent-os ready-admit 3481 {HEAD[:-1]} {BODY}",
        f"/agent-os ready-admit 3481 {HEAD.upper()} {BODY}",
        f"/agent-os ready-admit 3481 {HEAD} {BODY[:-1]}",
        f"/agent-os ready-admit 3481 {HEAD} {BODY} extra",
        f"/agent-os ready-admit 3481 {HEAD} {BODY}; rm -rf /",
        f"/agent-os ready-admit 3481 {HEAD} {BODY}\n",
        f"/agent-os ready-admit 3481 {HEAD}",
        "/agent-os ready-admit",
        f"/agent-os ready-admit https://github.com/Blummer92/agent-os/pull/3481 {HEAD} {BODY}",
        f"/agent-os ready-admit 12345678901 {HEAD} {BODY}",
    ],
)
def test_malformed_or_extended_requests_are_never_accepted(body: str) -> None:
    result = admit(event(body))
    assert result.status != "accepted"
    assert result.ready_admission_pr_number_or_none is None


def test_forged_actor_wrong_repo_pr_comment_and_rerun_fail_closed() -> None:
    assert admit(event(TRIGGER, actor="mallory")).reason == "actor-not-allowed"
    assert admit(event(TRIGGER, sender="mallory")).reason == "actor-evidence-mismatch"
    assert admit(event(TRIGGER, repo="Blummer92/other")).reason == "repository-mismatch"
    assert admit(event(TRIGGER, pull_request=True)).reason == "pull-request-comment"
    assert admit(event(TRIGGER), run_attempt=2).reason == "workflow-rerun"
    for blocked in (admit(event(TRIGGER, actor="mallory")), admit(event(TRIGGER), run_attempt=2)):
        assert blocked.ready_admission_head_sha_or_none is None


def test_ready_envelope_is_not_routed_to_codespaces_or_gce() -> None:
    transport = admit(event(TRIGGER)).to_dict()
    route = resolve_ingress_route(transport)
    assert route["preferred"] == "none"
    assert route["gce_fallback_allowed"] is False
