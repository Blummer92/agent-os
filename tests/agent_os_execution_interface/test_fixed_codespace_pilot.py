"""#3333 fixed host-ingress consumer: safe defaults and bounded identity."""
from __future__ import annotations

from scripts.agent_os_execution_interface.fixed_codespace_pilot import (
    ACCEPTED_REASON,
    ISSUE_NUMBER,
    OPERATION_ID,
    consume_fixed_codespace_pilot,
)
from workflow_scheduler.governance.github_issue_comment_ingress import (
    admit_issue_comment_event,
)

REPO = "Blummer92/agent-os"
SHA = "a" * 40
HANDOFF = "executor-handoff:" + "b" * 64
TRIGGER = f"/agent-os codespace-implementation {HANDOFF} {SHA}"


def event(body=TRIGGER, *, issue=ISSUE_NUMBER, actor="Blummer92", action="created"):
    return {
        "action": action,
        "repository": {"full_name": REPO},
        "issue": {"number": issue},
        "comment": {"id": 101, "body": body, "user": {"login": actor}},
        "sender": {"login": actor},
    }


def admit(payload, *, attempt=1):
    return admit_issue_comment_event(
        payload, expected_repository=REPO,
        allowed_actor="Blummer92", run_attempt=attempt,
    )


def test_fixed_operation_is_admitted_only_as_transport_evidence():
    result = admit(event())
    assert result.status == "accepted"
    assert result.reason == ACCEPTED_REASON
    assert result.codespace_implementation_handoff_id_or_none == HANDOFF
    assert result.codespace_implementation_sha_or_none == SHA
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False
    receipt = consume_fixed_codespace_pilot(result.to_dict())
    assert receipt["status"] == "needs-decision"
    assert receipt["reason_codes"] == ["canonical-admission-provider-unavailable"]
    assert receipt["request_id"] is None
    assert receipt["side_effects_performed"] is False
    assert receipt["operation_id"] == OPERATION_ID


def test_duplicate_event_uses_deterministic_identity():
    first = admit(event()).to_dict()
    second = event()
    second["comment"]["id"] = 102
    other = admit(second).to_dict()
    assert first["logical_trigger_id_or_none"] == other["logical_trigger_id_or_none"]


def test_wrong_issue_cannot_invoke_fixed_operation():
    result = admit(event(issue=3334))
    assert result.status == "blocked"
    assert result.reason == "codespace-implementation-issue-mismatch"


def test_nonowner_and_rerun_are_blocked():
    assert admit(event(actor="untrusted")).reason == "actor-not-allowed"
    assert admit(event(), attempt=2).reason == "workflow-rerun"


def test_extra_tokens_and_shell_syntax_are_rejected():
    for body in (
        TRIGGER + " --force",
        TRIGGER + "; git push origin main",
        TRIGGER.replace(SHA, "not-a-sha"),
        TRIGGER.replace(HANDOFF, "arbitrary-command"),
        "/agent-os codespace-implementation",
    ):
        result = admit(event(body))
        assert result.status != "accepted"


def test_noncanonical_or_tampered_receipt_fails_closed():
    accepted = admit(event()).to_dict()
    for field, value in (
        ("repository", "someone/else"),
        ("issue_number", 3334),
        ("actor", "mallory"),
        ("run_attempt", 2),
        ("codespace_implementation_sha_or_none", "bad"),
        ("codespace_implementation_handoff_id_or_none", "bad"),
        ("status", "ignored"),
        ("reason", "accepted-discovery-envelope"),
    ):
        tampered = {**accepted, field: value}
        result = consume_fixed_codespace_pilot(tampered)
        assert result["status"] == "blocked"
        assert result["reason_codes"] == ["invalid-fixed-operation-envelope"]
        assert result["side_effects_performed"] is False


def test_existing_discovery_ingress_unchanged():
    result = admit(event("/agent-os discover"))
    assert result.status == "accepted"
    assert result.reason == "accepted-discovery-envelope"
    assert result.codespace_implementation_handoff_id_or_none is None


def test_incomplete_production_host_binding_is_refused():
    transport = admit(event()).to_dict()
    result = consume_fixed_codespace_pilot(
        transport,
        descriptor_loader=lambda handoff: object(),
        current_resolver=object(),
        lease_reader=object(),
        codespace_selection=object(),
        evaluated_at="2026-10-09T19:00:00Z",
    )
    assert result["status"] == "blocked"
    assert result["reason_codes"] == ["canonical-host-binding-incomplete"]
    assert result["side_effects_performed"] is False
    assert result["request_id"] is None
