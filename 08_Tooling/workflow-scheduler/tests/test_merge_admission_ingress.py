"""#3463: fixed, non-authorizing merge admission trigger transport.

The ingress grants no merge, lifecycle, workflow, issue closure or production
authority. It only carries bounded immutable selectors to a separate evaluator.
"""
from __future__ import annotations

import pytest

from workflow_scheduler.governance.codespaces_first_route import resolve_ingress_route
from workflow_scheduler.governance.github_issue_comment_ingress import admit_issue_comment_event

REPOSITORY = "Blummer92/agent-os"
HEAD = "a" * 40
BODY = "b" * 64
TRIGGER = f"/agent-os merge-admit 3659 {HEAD} {BODY} merge"


def event(
    body: str,
    *,
    actor: str = "Blummer92",
    sender: str | None = None,
    repository: str = REPOSITORY,
    pull_request: bool = False,
) -> dict[str, object]:
    issue: dict[str, object] = {"number": 3463}
    if pull_request:
        issue["pull_request"] = {}
    return {
        "action": "created",
        "repository": {"full_name": repository},
        "issue": issue,
        "comment": {"id": 99111, "body": body, "user": {"login": actor}},
        "sender": {"login": sender if sender is not None else actor},
    }


def admit(payload: object, *, attempt: int = 1):
    return admit_issue_comment_event(
        payload,
        expected_repository=REPOSITORY,
        allowed_actor="Blummer92",
        run_attempt=attempt,
    )


def test_exact_merge_trigger_is_only_transport_evidence() -> None:
    result = admit(event(TRIGGER))
    assert result.status == "accepted"
    assert result.reason == "accepted-merge-admission-envelope"
    assert result.merge_admission_pr_number_or_none == 3659
    assert result.merge_admission_head_sha_or_none == HEAD
    assert result.merge_admission_body_sha256_or_none == BODY
    assert result.merge_admission_method_or_none == "merge"
    assert result.logical_trigger_id_or_none
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False
    serialized = result.to_dict()
    assert serialized["execution_authorized"] is False
    assert serialized["merge_admission_method_or_none"] == "merge"
    assert serialized["merge_admission_pr_number_or_none"] == 3659
    assert all(not k.startswith("merge_authorized") for k in serialized)


def test_trigger_binds_pr_head_body_and_method() -> None:
    original = admit(event(TRIGGER)).logical_trigger_id_or_none
    cases = [
        f"/agent-os merge-admit 3660 {HEAD} {BODY} merge",
        f"/agent-os merge-admit 3659 {'c' * 40} {BODY} merge",
        f"/agent-os merge-admit 3659 {HEAD} {'d' * 64} merge",
        f"/agent-os merge-admit 3659 {HEAD} {BODY} squash",
        f"/agent-os merge-admit 3659 {HEAD} {BODY} rebase",
    ]
    ids = {original}
    for case in cases:
        result = admit(event(case))
        assert result.status == "accepted"
        ids.add(result.logical_trigger_id_or_none)
    assert len(ids) == len(cases) + 1
    assert original == admit(event(TRIGGER)).logical_trigger_id_or_none


@pytest.mark.parametrize(
    "body",
    [
        f"/agent-os merge-admit 0 {HEAD} {BODY} merge",
        f"/agent-os merge-admit 03659 {HEAD} {BODY} merge",
        f"/agent-os merge-admit 3659 {HEAD[:-1]} {BODY} merge",
        f"/agent-os merge-admit 3659 {HEAD.upper()} {BODY} merge",
        f"/agent-os merge-admit 3659 {HEAD} {BODY[:-1]} merge",
        f"/agent-os merge-admit 3659 {HEAD} {BODY} MERGE",
        f"/agent-os merge-admit 3659 {HEAD} {BODY} merge --force",
        f"/agent-os merge-admit 3659 {HEAD} {BODY} merge\n",
        f"/agent-os merge-admit 3659 {HEAD} {BODY} merge; echo hi",
        "/agent-os merge-admit",
        f"/agent-os merge-admit https://github.com/pull/3659 {HEAD} {BODY} merge",
    ],
)
def test_malformed_trigger_fails_closed(body: str) -> None:
    result = admit(event(body))
    assert result.status != "accepted"
    assert result.merge_admission_pr_number_or_none is None


def test_actor_identity_repository_event_and_retry_are_rejected() -> None:
    for payload, attempt in [
        (event(TRIGGER, actor="mallory"), 1),
        (event(TRIGGER, sender="mallory"), 1),
        (event(TRIGGER, repository="Blummer92/other"), 1),
        (event(TRIGGER, pull_request=True), 1),
        (event(TRIGGER), 2),
    ]:
        result = admit(payload, attempt=attempt)
        assert result.status != "accepted"
        assert result.merge_admission_head_sha_or_none is None
        assert result.execution_authorized is False


def test_merge_command_does_not_dispatch_codespaces_or_gce() -> None:
    receipt = admit(event(TRIGGER)).to_dict()
    route = resolve_ingress_route(receipt)
    assert route["preferred"] == "none"
    assert route["gce_fallback_allowed"] is False
