from __future__ import annotations

import json
from pathlib import Path

from workflow_scheduler.governance.github_issue_comment_ingress import (
    admit_issue_comment_event,
    main,
)

REPOSITORY = "Blummer92/agent-os"
ACTOR = "Blummer92"
HANDOFF = "executor-handoff:" + "a" * 64
DEV_SHA = "b" * 40
DEV_TRIGGER = f"/agent-os dev-validate agent/1271-validation-profile-path-coverage {DEV_SHA} remote-validation-suite"
MATERIALS_DEV_TRIGGER = f"/agent-os dev-validate agent/1416-curriculum-evidence-materials-context {DEV_SHA} instructional-materials-current-curriculum"


def event(body: str, *, action: str = "created", actor: str = ACTOR) -> dict[str, object]:
    return {
        "action": action,
        "repository": {"full_name": REPOSITORY},
        "issue": {"number": 1203},
        "comment": {"id": 9981, "body": body, "user": {"login": actor}},
        "sender": {"login": actor},
    }


def admit(payload: object, *, run_attempt: int = 1):
    return admit_issue_comment_event(
        payload,
        expected_repository=REPOSITORY,
        allowed_actor=ACTOR,
        run_attempt=run_attempt,
    )


def test_exact_trigger_is_accepted_but_never_authorizes_or_invokes() -> None:
    result = admit(event(f"/agent-os resume {HANDOFF}"))
    assert result.status == "accepted"
    assert result.reason == "accepted-envelope"
    assert result.handoff_id_or_none == HANDOFF
    assert result.logical_trigger_id_or_none is not None
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False


def test_extra_tokens_are_rejected() -> None:
    result = admit(event(f"/agent-os resume {HANDOFF} --force"))
    assert (result.status, result.reason) == ("ignored", "malformed-trigger")


def test_shell_syntax_cannot_enter_the_identifier() -> None:
    result = admit(event(f"/agent-os resume {HANDOFF}; rm -rf /"))
    assert (result.status, result.reason) == ("ignored", "malformed-trigger")
    assert result.handoff_id_or_none is None


def test_unauthorized_actor_is_blocked() -> None:
    result = admit(event(f"/agent-os resume {HANDOFF}", actor="mallory"))
    assert (result.status, result.reason) == ("blocked", "actor-not-allowed")


def test_sender_and_comment_actor_must_match() -> None:
    payload = event(f"/agent-os resume {HANDOFF}")
    payload["sender"] = {"login": "mallory"}
    result = admit(payload)
    assert (result.status, result.reason) == ("blocked", "actor-evidence-mismatch")


def test_rerun_is_not_executable_transport_authority() -> None:
    result = admit(event(f"/agent-os resume {HANDOFF}"), run_attempt=2)
    assert (result.status, result.reason) == ("blocked", "workflow-rerun")


def test_edited_event_is_blocked() -> None:
    result = admit(event(f"/agent-os resume {HANDOFF}", action="edited"))
    assert (result.status, result.reason) == ("blocked", "event-not-created")


def test_pull_request_comment_is_ignored() -> None:
    payload = event(f"/agent-os resume {HANDOFF}")
    payload["issue"]["pull_request"] = {"url": "https://example.invalid/pr/1"}
    result = admit(payload)
    assert (result.status, result.reason) == ("ignored", "pull-request-comment")


def test_repository_mismatch_is_blocked() -> None:
    payload = event(f"/agent-os resume {HANDOFF}")
    payload["repository"] = {"full_name": "someone/else"}
    result = admit(payload)
    assert (result.status, result.reason) == ("blocked", "repository-mismatch")


def test_duplicate_comments_share_one_logical_trigger_identity() -> None:
    first = event(f"/agent-os resume {HANDOFF}")
    second = event(f"/agent-os resume {HANDOFF}")
    second["comment"]["id"] = 9982
    assert admit(first).logical_trigger_id_or_none == admit(second).logical_trigger_id_or_none


def test_different_handoffs_have_different_logical_trigger_identities() -> None:
    first = admit(event(f"/agent-os resume {HANDOFF}"))
    other = "executor-handoff:" + "b" * 64
    second = admit(event(f"/agent-os resume {other}"))
    assert first.logical_trigger_id_or_none != second.logical_trigger_id_or_none


def test_result_never_copies_comment_body() -> None:
    body = f"/agent-os resume {HANDOFF}"
    result = admit(event(body))
    encoded = json.dumps(result.to_dict(), sort_keys=True)
    assert body not in encoded


def test_cli_writes_bounded_canonical_json(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    output_path = tmp_path / "out" / "transport.json"
    event_path.write_text(json.dumps(event(f"/agent-os resume {HANDOFF}")), encoding="utf-8")
    assert main([
        "--event", str(event_path),
        "--repository", REPOSITORY,
        "--allowed-actor", ACTOR,
        "--run-attempt", "1",
        "--output", str(output_path),
    ]) == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "accepted"
    assert payload["execution_authorized"] is False
    assert payload["scheduler_invoked"] is False
    assert payload["side_effects_performed"] is False


def test_exact_discovery_trigger_is_accepted_without_handoff_authority() -> None:
    result = admit(event("/agent-os discover"))
    assert result.status == "accepted"
    assert result.reason == "accepted-discovery-envelope"
    assert result.handoff_id_or_none is None
    assert result.logical_trigger_id_or_none is not None
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False


def test_discovery_trigger_rejects_arguments_and_fake_handoff_text() -> None:
    result = admit(event(f"/agent-os discover {HANDOFF}"))
    assert (result.status, result.reason) == ("ignored", "malformed-trigger")
    assert result.handoff_id_or_none is None


def test_duplicate_discovery_comments_share_logical_identity() -> None:
    first = event("/agent-os discover")
    second = event("/agent-os discover")
    second["comment"]["id"] = 9982
    assert admit(first).logical_trigger_id_or_none == admit(second).logical_trigger_id_or_none


def test_exact_dev_validation_trigger_is_accepted_but_non_authorizing() -> None:
    result = admit(event(DEV_TRIGGER))
    assert result.status == "accepted"
    assert result.reason == "accepted-dev-validation-envelope"
    assert result.dev_validation_branch_or_none == "agent/1271-validation-profile-path-coverage"
    assert result.dev_validation_sha_or_none == DEV_SHA
    assert result.dev_validation_id_or_none == "remote-validation-suite"
    assert result.handoff_id_or_none is None
    assert result.logical_trigger_id_or_none is not None
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False


def test_fixed_materials_dev_validation_trigger_is_accepted_but_non_authorizing() -> None:
    result = admit(event(MATERIALS_DEV_TRIGGER))
    assert result.status == "accepted"
    assert result.reason == "accepted-dev-validation-envelope"
    assert result.dev_validation_branch_or_none == "agent/1416-curriculum-evidence-materials-context"
    assert result.dev_validation_sha_or_none == DEV_SHA
    assert result.dev_validation_id_or_none == "instructional-materials-current-curriculum"
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False


def test_dev_validation_rejects_arbitrary_command_and_protected_branch() -> None:
    arbitrary = admit(event(f"{DEV_TRIGGER} ; rm -rf /"))
    protected = admit(event(f"/agent-os dev-validate main {DEV_SHA} remote-validation-suite"))
    unknown = admit(event(f"/agent-os dev-validate agent/x {DEV_SHA} arbitrary-suite"))
    materials_extra = admit(event(f"{MATERIALS_DEV_TRIGGER} tests/test_other.py"))
    assert (arbitrary.status, arbitrary.reason) == ("ignored", "malformed-trigger")
    assert (protected.status, protected.reason) == ("ignored", "malformed-trigger")
    assert (unknown.status, unknown.reason) == ("ignored", "malformed-trigger")
    assert (materials_extra.status, materials_extra.reason) == ("ignored", "malformed-trigger")


def test_duplicate_dev_validation_comments_share_identity_but_sha_change_does_not() -> None:
    first = admit(event(DEV_TRIGGER))
    duplicate_event = event(DEV_TRIGGER)
    duplicate_event["comment"]["id"] = 9982
    duplicate = admit(duplicate_event)
    changed = admit(event(DEV_TRIGGER.replace(DEV_SHA, "c" * 40)))
    assert first.logical_trigger_id_or_none == duplicate.logical_trigger_id_or_none
    assert first.logical_trigger_id_or_none != changed.logical_trigger_id_or_none


def test_validation_identity_is_part_of_logical_trigger_identity() -> None:
    remote = admit(event(DEV_TRIGGER))
    materials = admit(event(MATERIALS_DEV_TRIGGER.replace("agent/1416-curriculum-evidence-materials-context", "agent/1271-validation-profile-path-coverage")))
    assert remote.logical_trigger_id_or_none != materials.logical_trigger_id_or_none
