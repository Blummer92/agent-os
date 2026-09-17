from __future__ import annotations

from workflow_scheduler.governance.github_issue_comment_ingress import (
    RULESET_ADMIN_ISSUE,
    admit_issue_comment_event,
)

REPOSITORY = "Blummer92/agent-os"
ACTOR = "Blummer92"
DIGEST = "a" * 64


def event(body: str, *, issue_number: int = RULESET_ADMIN_ISSUE) -> dict[str, object]:
    return {
        "action": "created",
        "repository": {"full_name": REPOSITORY},
        "issue": {"number": issue_number},
        "comment": {"id": 1, "body": body, "user": {"login": ACTOR}},
        "sender": {"login": ACTOR},
    }


def admit(body: str, *, issue_number: int = RULESET_ADMIN_ISSUE):
    return admit_issue_comment_event(
        event(body, issue_number=issue_number),
        expected_repository=REPOSITORY,
        allowed_actor=ACTOR,
        run_attempt=1,
    )


def test_exact_ruleset_admin_trigger_is_accepted_only_on_authorization_issue() -> None:
    result = admit(f"/agent-os apply-required-validation-gate {DIGEST}")
    assert (result.status, result.reason) == ("accepted", "accepted-ruleset-admin-envelope")
    assert result.issue_number == 2234
    assert result.ruleset_prestate_sha256_or_none == DIGEST
    assert result.handoff_id_or_none is None
    assert result.logical_trigger_id_or_none is not None
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False


def test_ruleset_admin_trigger_is_blocked_on_other_issue() -> None:
    result = admit(f"/agent-os apply-required-validation-gate {DIGEST}", issue_number=2598)
    assert (result.status, result.reason) == ("blocked", "ruleset-admin-issue-mismatch")
    assert result.ruleset_prestate_sha256_or_none is None


def test_ruleset_admin_trigger_rejects_noncanonical_digest() -> None:
    for value in ("A" * 64, "a" * 63, "g" * 64, DIGEST + "x"):
        result = admit(f"/agent-os apply-required-validation-gate {value}")
        assert (result.status, result.reason) == ("ignored", "malformed-trigger")
        assert result.ruleset_prestate_sha256_or_none is None


def test_ruleset_admin_identity_survives_transport_projection() -> None:
    result = admit(f"/agent-os apply-required-validation-gate {DIGEST}")
    payload = result.to_dict()
    assert payload["ruleset_prestate_sha256_or_none"] == DIGEST
    assert payload["execution_authorized"] is False
    assert payload["side_effects_performed"] is False
