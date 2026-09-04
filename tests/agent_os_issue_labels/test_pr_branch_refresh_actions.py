from __future__ import annotations

from scripts.agent_os_issue_labels.pr_branch_refresh_actions import (
    classify_branch_refresh_actions_trigger,
)

WORKFLOW_REF = (
    "Blummer92/agent-os/.github/workflows/"
    "agent-os-governed-invocation.yml@refs/heads/main"
)


def _event(body: object = "/agent-os refresh-pr 1619") -> dict[str, object]:
    return {
        "action": "created",
        "issue": {"number": 1807, "pull_request": None},
        "comment": {
            "body": body,
            "user": {"login": "Blummer92", "id": 32861845},
        },
        "repository": {"id": 1289370915, "full_name": "Blummer92/agent-os"},
    }


def _classify(event: dict[str, object], **overrides: object):
    values = {
        "repository": "Blummer92/agent-os",
        "repository_id": 1289370915,
        "ref": "refs/heads/main",
        "workflow_ref": WORKFLOW_REF,
        "run_attempt": 1,
    }
    values.update(overrides)
    return classify_branch_refresh_actions_trigger(event, **values)


def test_exact_owner_trigger_selects_only_pr_number_and_grants_no_authority() -> None:
    result = _classify(_event())
    assert result.status == "accepted"
    assert result.pr_number == 1619
    assert result.repository == "Blummer92/agent-os"
    assert result.branch_refresh_authorized is False
    assert result.label_write_authorized is False
    assert result.merge_authorized is False
    assert result.issue_closure_authorized is False
    assert result.side_effects_performed is False


def test_trigger_rejects_arbitrary_arguments_and_authority_injection() -> None:
    for body in (
        "/agent-os refresh-pr 1619 --force",
        "/agent-os refresh-pr 1619 branch=main",
        "/agent-os refresh-pr 1619 authorized=true",
        "/agent-os refresh-pr Blummer92/agent-os#1619",
        "/agent-os refresh-pr 1619; echo token",
        "/agent-os refresh-pr 0",
    ):
        result = _classify(_event(body))
        assert result.status == "blocked"
        assert result.pr_number is None


def test_trigger_is_owner_repository_main_workflow_and_first_attempt_bound() -> None:
    event = _event()
    bad_actor = _event()
    bad_actor["comment"] = {
        "body": "/agent-os refresh-pr 1619",
        "user": {"login": "someone", "id": 7},
    }
    cases = (
        _classify(bad_actor),
        _classify(event, repository="other/repo"),
        _classify(event, repository_id=7),
        _classify(event, ref="refs/heads/feature"),
        _classify(event, workflow_ref="other/workflow@refs/heads/main"),
        _classify(event, run_attempt=2),
    )
    assert all(result.status == "blocked" for result in cases)


def test_pr_conversation_comment_is_not_a_refresh_trigger() -> None:
    event = _event()
    event["issue"] = {"number": 1619, "pull_request": {"url": "https://example.invalid"}}
    result = _classify(event)
    assert result.status == "blocked"
    assert result.reason == "pr-comment-not-allowed"


def test_native_authentication_never_becomes_refresh_authorization() -> None:
    result = _classify(_event())
    assert result.status == "accepted"
    assert result.branch_refresh_authorized is False
    assert result.label_write_authorized is False
