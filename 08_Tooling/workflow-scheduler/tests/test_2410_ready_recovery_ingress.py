"""Contract regressions for the #2410 bounded Ready-recovery ingress grammar.

A recover-ready comment carries only immutable selectors. Admission here is
transport evidence, never execution authorization: the dispatch module and
the validation workflow each re-verify every binding before any recovery.
"""
from __future__ import annotations

from workflow_scheduler.governance.github_issue_comment_ingress import (
    admit_issue_comment_event,
)

REPOSITORY = "Blummer92/agent-os"
OWNER = "Blummer92"
SERVICE = "chatgpt-codex-connector[bot]"
HEAD_SHA = "a" * 40
MAIN_SHA = "b" * 40
WORKFLOW_SHA = "c" * 40
SOURCE_RUN_ID = 40150153359
TRIGGER = (
    f"/agent-os recover-ready 3723 {HEAD_SHA} {MAIN_SHA} {WORKFLOW_SHA} {SOURCE_RUN_ID}"
)


def event(body: str, *, actor: str = SERVICE) -> dict[str, object]:
    return {
        "action": "created",
        "repository": {"full_name": REPOSITORY},
        "issue": {"number": 2410},
        "comment": {"id": 7001, "body": body, "user": {"login": actor}},
        "sender": {"login": actor},
    }


def admit(payload: object, *, run_attempt: int = 1, recovery_actor: str | None = SERVICE):
    return admit_issue_comment_event(
        payload,
        expected_repository=REPOSITORY,
        allowed_actor=OWNER,
        run_attempt=run_attempt,
        ready_recovery_service_actor=recovery_actor,
    )


def test_valid_recover_ready_trigger_is_accepted_but_never_authorizes() -> None:
    result = admit(event(TRIGGER))
    assert result.status == "accepted"
    assert result.reason == "accepted-ready-recovery-envelope"
    assert result.ready_recovery_pr_number_or_none == 3723
    assert result.ready_recovery_head_sha_or_none == HEAD_SHA
    assert result.ready_recovery_main_sha_or_none == MAIN_SHA
    assert result.ready_recovery_workflow_sha_or_none == WORKFLOW_SHA
    assert result.ready_recovery_source_run_id_or_none == SOURCE_RUN_ID
    assert result.logical_trigger_id_or_none is not None
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False


def test_owner_actor_is_admitted() -> None:
    result = admit(event(TRIGGER, actor=OWNER))
    assert (result.status, result.reason) == ("accepted", "accepted-ready-recovery-envelope")


def test_trigger_id_is_deterministic_and_binding_sensitive() -> None:
    first = admit(event(TRIGGER))
    second = admit(event(TRIGGER))
    assert first.logical_trigger_id_or_none == second.logical_trigger_id_or_none
    variants = (
        f"/agent-os recover-ready 3724 {HEAD_SHA} {MAIN_SHA} {WORKFLOW_SHA} {SOURCE_RUN_ID}",
        f"/agent-os recover-ready 3723 {'d' * 40} {MAIN_SHA} {WORKFLOW_SHA} {SOURCE_RUN_ID}",
        f"/agent-os recover-ready 3723 {HEAD_SHA} {'e' * 40} {WORKFLOW_SHA} {SOURCE_RUN_ID}",
        f"/agent-os recover-ready 3723 {HEAD_SHA} {MAIN_SHA} {'f' * 40} {SOURCE_RUN_ID}",
        f"/agent-os recover-ready 3723 {HEAD_SHA} {MAIN_SHA} {WORKFLOW_SHA} 40150153360",
    )
    for body in variants:
        assert admit(event(body)).logical_trigger_id_or_none != first.logical_trigger_id_or_none
    other_issue = admit_issue_comment_event(
        {
            "action": "created",
            "repository": {"full_name": REPOSITORY},
            "issue": {"number": 2411},
            "comment": {"id": 7002, "body": TRIGGER, "user": {"login": SERVICE}},
            "sender": {"login": SERVICE},
        },
        expected_repository=REPOSITORY,
        allowed_actor=OWNER,
        run_attempt=1,
        ready_recovery_service_actor=SERVICE,
    )
    assert other_issue.logical_trigger_id_or_none != first.logical_trigger_id_or_none


def test_service_actor_is_scoped_to_recover_ready_only() -> None:
    for body in (
        f"/agent-os validate-draft 3723 {HEAD_SHA}",
        f"/agent-os ready-admit 3723 {HEAD_SHA} {'d' * 64}",
        "/agent-os discover",
    ):
        result = admit(event(body))
        assert (result.status, result.reason) == ("blocked", "actor-not-allowed"), body


def test_unauthorized_actor_and_sender_mismatch_are_blocked() -> None:
    result = admit(event(TRIGGER, actor="mallory"))
    assert (result.status, result.reason) == ("blocked", "actor-not-allowed")
    payload = event(TRIGGER)
    payload["sender"] = {"login": OWNER}  # type: ignore[assignment]
    result = admit(payload)
    assert (result.status, result.reason) == ("blocked", "actor-evidence-mismatch")


def test_rerun_attempt_is_blocked() -> None:
    result = admit(event(TRIGGER), run_attempt=2)
    assert (result.status, result.reason) == ("blocked", "workflow-rerun")


def test_extra_tokens_and_shell_syntax_are_rejected() -> None:
    for body in (TRIGGER + " --force", TRIGGER + "; rm -rf /", TRIGGER + " extra"):
        result = admit(event(body))
        assert (result.status, result.reason) == ("ignored", "malformed-trigger"), body
        assert result.ready_recovery_pr_number_or_none is None


def test_malformed_selectors_are_rejected() -> None:
    for body in (
        f"/agent-os recover-ready 0 {HEAD_SHA} {MAIN_SHA} {WORKFLOW_SHA} {SOURCE_RUN_ID}",
        f"/agent-os recover-ready 03723 {HEAD_SHA} {MAIN_SHA} {WORKFLOW_SHA} {SOURCE_RUN_ID}",
        f"/agent-os recover-ready 3723 {'a' * 39} {MAIN_SHA} {WORKFLOW_SHA} {SOURCE_RUN_ID}",
        f"/agent-os recover-ready 3723 {'A' * 40} {MAIN_SHA} {WORKFLOW_SHA} {SOURCE_RUN_ID}",
        f"/agent-os recover-ready 3723 {HEAD_SHA} {'g' * 40} {WORKFLOW_SHA} {SOURCE_RUN_ID}",
        f"/agent-os recover-ready 3723 {HEAD_SHA} {MAIN_SHA} {WORKFLOW_SHA} 0",
        f"/agent-os recover-ready 3723 {HEAD_SHA} {MAIN_SHA} {SOURCE_RUN_ID}",
        f"/agent-os recover-ready {HEAD_SHA} {MAIN_SHA} {WORKFLOW_SHA} {SOURCE_RUN_ID}",
    ):
        result = admit(event(body))
        assert (result.status, result.reason) == ("ignored", "malformed-trigger"), body
