from __future__ import annotations

from workflow_scheduler.governance.github_issue_comment_ingress import (
    admit_issue_comment_event,
)

REPOSITORY = "Blummer92/agent-os"
ACTOR = "Blummer92"
HEAD_SHA = "a" * 40
TRIGGER = f"/agent-os validate-draft 2411 {HEAD_SHA}"


def event(body: str, *, action: str = "created", actor: str = ACTOR) -> dict[str, object]:
    return {
        "action": action,
        "repository": {"full_name": REPOSITORY},
        "issue": {"number": 2410},
        "comment": {"id": 7001, "body": body, "user": {"login": actor}},
        "sender": {"login": actor},
    }


def admit(payload: object, *, run_attempt: int = 1):
    return admit_issue_comment_event(
        payload,
        expected_repository=REPOSITORY,
        allowed_actor=ACTOR,
        run_attempt=run_attempt,
    )


def test_valid_draft_validation_trigger_is_accepted_but_never_authorizes() -> None:
    result = admit(event(TRIGGER))
    assert result.status == "accepted"
    assert result.reason == "accepted-draft-validation-envelope"
    assert result.draft_validation_pr_number_or_none == 2411
    assert result.draft_validation_head_sha_or_none == HEAD_SHA
    assert result.logical_trigger_id_or_none is not None
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False


def test_trigger_id_is_deterministic_for_duplicate_detection() -> None:
    first = admit(event(TRIGGER))
    second = admit(event(TRIGGER))
    assert first.logical_trigger_id_or_none == second.logical_trigger_id_or_none
    other = admit(event(f"/agent-os validate-draft 2412 {HEAD_SHA}"))
    assert other.logical_trigger_id_or_none != first.logical_trigger_id_or_none


def test_extra_tokens_and_shell_syntax_are_rejected() -> None:
    for body in (TRIGGER + " --force", TRIGGER + "; rm -rf /", TRIGGER + " extra"):
        result = admit(event(body))
        assert (result.status, result.reason) == ("ignored", "malformed-trigger")
        assert result.draft_validation_pr_number_or_none is None


def test_malformed_selectors_are_rejected() -> None:
    for body in (
        f"/agent-os validate-draft 0 {HEAD_SHA}",  # PR number may not be zero
        f"/agent-os validate-draft 02411 {HEAD_SHA}",  # no leading zeros
        "/agent-os validate-draft 2411 " + "a" * 39,  # short SHA
        "/agent-os validate-draft 2411 " + "A" * 40,  # SHA is lowercase hex only
        "/agent-os validate-draft 2411 " + "g" * 40,  # non-hex
        "/agent-os validate-draft " + HEAD_SHA,  # missing PR number
    ):
        result = admit(event(body))
        assert (result.status, result.reason) == ("ignored", "malformed-trigger"), body


def test_unauthorized_actor_is_blocked() -> None:
    result = admit(event(TRIGGER, actor="mallory"))
    assert (result.status, result.reason) == ("blocked", "actor-not-allowed")


def test_sender_and_comment_actor_must_match() -> None:
    payload = event(TRIGGER)
    payload["sender"] = {"login": "mallory"}
    result = admit(payload)
    assert (result.status, result.reason) == ("blocked", "actor-evidence-mismatch")


def test_rerun_is_blocked() -> None:
    result = admit(event(TRIGGER), run_attempt=2)
    assert (result.status, result.reason) == ("blocked", "workflow-rerun")


def test_edited_comment_is_blocked() -> None:
    result = admit(event(TRIGGER, action="edited"))
    assert (result.status, result.reason) == ("blocked", "event-not-created")


def test_pull_request_comment_is_ignored() -> None:
    payload = event(TRIGGER)
    payload["issue"] = {"number": 2410, "pull_request": {"url": "https://example.invalid"}}
    result = admit(payload)
    assert (result.status, result.reason) == ("ignored", "pull-request-comment")


def test_wrong_repository_is_blocked() -> None:
    payload = event(TRIGGER)
    payload["repository"] = {"full_name": "mallory/agent-os"}
    result = admit(payload)
    assert (result.status, result.reason) == ("blocked", "repository-mismatch")


def test_validate_draft_does_not_collide_with_validate_first_run() -> None:
    first_run = admit(event(f"/agent-os validate-first-run {HEAD_SHA}"))
    assert first_run.reason == "accepted-first-run-validation-envelope"
    assert first_run.draft_validation_pr_number_or_none is None


def test_transport_dict_carries_draft_validation_fields() -> None:
    payload = admit(event(TRIGGER)).to_dict()
    assert payload["draft_validation_pr_number_or_none"] == 2411
    assert payload["draft_validation_head_sha_or_none"] == HEAD_SHA
    assert payload["execution_authorized"] is False
