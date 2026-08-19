from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflow_scheduler.governance.github_issue_comment_ingress import (
    admit_issue_comment_event,
    main,
)

REPOSITORY = "Blummer92/agent-os"
ACTOR = "Blummer92"
HANDOFF = "executor-handoff:" + "a" * 64


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


DISCOVERY = "/agent-os discover-handoff"


def test_discovery_trigger_is_accepted_with_envelope_identity_only() -> None:
    result = admit(event(DISCOVERY))
    assert result.status == "accepted"
    assert result.reason == "accepted-envelope"
    assert result.operation_or_none == "discover-handoff"
    # Identity comes from the envelope, never from the comment body.
    assert result.repository == REPOSITORY
    assert result.issue_number == 1203
    assert result.handoff_id_or_none is None
    assert result.logical_trigger_id_or_none is not None
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False


def test_resume_trigger_still_reports_the_resume_operation() -> None:
    result = admit(event(f"/agent-os resume {HANDOFF}"))
    assert result.operation_or_none == "resume"
    assert result.handoff_id_or_none == HANDOFF


def test_discovery_and_resume_have_distinct_logical_trigger_identities() -> None:
    discovery = admit(event(DISCOVERY))
    resume = admit(event(f"/agent-os resume {HANDOFF}"))
    assert (
        discovery.logical_trigger_id_or_none != resume.logical_trigger_id_or_none
    )
    assert discovery.logical_trigger_id_or_none.startswith(
        "issue-comment-discovery-trigger:"
    )


def test_replayed_discovery_shares_one_logical_trigger_identity() -> None:
    first = event(DISCOVERY)
    second = event(DISCOVERY)
    second["comment"]["id"] = 9983
    assert (
        admit(first).logical_trigger_id_or_none
        == admit(second).logical_trigger_id_or_none
    )


def test_discovery_on_a_different_issue_has_a_different_identity() -> None:
    first = admit(event(DISCOVERY))
    other = event(DISCOVERY)
    other["issue"]["number"] = 1239
    assert first.logical_trigger_id_or_none != admit(other).logical_trigger_id_or_none


@pytest.mark.parametrize(
    "body",
    [
        f"{DISCOVERY} --store-root /etc",
        f"{DISCOVERY} Blummer92/agent-os 1284",
        f"{DISCOVERY}; rm -rf /",
        f"{DISCOVERY} {HANDOFF}",
        " /agent-os discover-handoff",
        "/agent-os discover-handoff ",
        "/agent-os discover",
    ],
)
def test_discovery_trigger_accepts_no_argument_whatsoever(body: str) -> None:
    result = admit(event(body))
    assert (result.status, result.reason) == ("ignored", "malformed-trigger")
    assert result.operation_or_none is None


def test_fake_handoff_in_prose_never_becomes_discovery_authority() -> None:
    fake = "executor-handoff:" + "f" * 64
    result = admit(event(f"Please resume {fake} now"))
    assert (result.status, result.reason) == ("ignored", "malformed-trigger")
    assert result.handoff_id_or_none is None
    assert result.operation_or_none is None


def test_unauthorized_actor_cannot_trigger_discovery() -> None:
    result = admit(event(DISCOVERY, actor="mallory"))
    assert (result.status, result.reason) == ("blocked", "actor-not-allowed")
    assert result.operation_or_none is None


def test_discovery_rerun_is_not_transport_authority() -> None:
    result = admit(event(DISCOVERY), run_attempt=2)
    assert (result.status, result.reason) == ("blocked", "workflow-rerun")


def test_discovery_result_never_copies_the_comment_body() -> None:
    encoded = json.dumps(admit(event(DISCOVERY)).to_dict(), sort_keys=True)
    assert DISCOVERY not in encoded
