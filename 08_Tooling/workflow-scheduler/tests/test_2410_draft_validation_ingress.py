from __future__ import annotations

from datetime import datetime, timezone

from workflow_scheduler.governance.draft_validation_dispatch import (
    PullRequestState,
    WorkflowRunSummary,
    execute_dispatch,
)
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


# --- GitHub Service Agent actor, admitted for validate-draft only -----------
# The service agent posts as the GitHub App identity below. It may initiate
# the read-only validate-draft operation; every other operation in the
# ingress grammar remains owner-only.

SERVICE_ACTOR = "chatgpt-codex-connector[bot]"


def admit_service(payload: object, *, run_attempt: int = 1):
    return admit_issue_comment_event(
        payload,
        expected_repository=REPOSITORY,
        allowed_actor=ACTOR,
        run_attempt=run_attempt,
        draft_validation_service_actor=SERVICE_ACTOR,
    )


def test_service_actor_validate_draft_is_accepted_but_never_authorizes() -> None:
    result = admit_service(event(TRIGGER, actor=SERVICE_ACTOR))
    assert result.status == "accepted"
    assert result.reason == "accepted-draft-validation-envelope"
    assert result.actor == SERVICE_ACTOR
    assert result.draft_validation_pr_number_or_none == 2411
    assert result.draft_validation_head_sha_or_none == HEAD_SHA
    assert result.logical_trigger_id_or_none is not None
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False


def test_service_actor_is_not_admitted_without_explicit_opt_in() -> None:
    # The default parser invocation (every other job) keeps the owner-only gate.
    result = admit(event(TRIGGER, actor=SERVICE_ACTOR))
    assert (result.status, result.reason) == ("blocked", "actor-not-allowed")


def test_service_actor_is_blocked_for_every_other_operation() -> None:
    other_commands = (
        "/agent-os discover",
        "/agent-os inspect-runtime",
        f"/agent-os resume executor-handoff:{'a' * 64}",
        f"/agent-os ready-admit 2411 {HEAD_SHA} {'b' * 64}",
        f"/agent-os merge-admit 2411 {HEAD_SHA} {'b' * 64} squash",
        f"/agent-os dev-validate agent/2411-example {HEAD_SHA} remote-validation-suite",
        "/agent-os notion-read req-123",
        f"/agent-os validate-first-run {HEAD_SHA}",
        f"/agent-os activate-first-publication pre-publication-evidence:{'a' * 64}",
        "/agent-os diagnose ppux-canva-cdp-readonly req-123",
        f"/agent-os project-ppux-prompts agent/2411-example {HEAD_SHA} {'a' * 64}",
    )
    for body in other_commands:
        # Sanity: each body is a real command the owner may issue.
        assert admit(event(body)).status == "accepted", body
        result = admit_service(event(body, actor=SERVICE_ACTOR))
        assert (result.status, result.reason) == ("blocked", "actor-not-allowed"), body


def test_service_actor_blocked_for_issue_bound_operations() -> None:
    # These two operations bind to fixed issue numbers; the service actor is
    # refused even on the correct issue, while the owner is accepted there.
    for issue_number, body in (
        (2234, f"/agent-os apply-required-validation-gate {'a' * 64}"),
        (3333, f"/agent-os codespace-implementation executor-handoff:{'a' * 64} {HEAD_SHA}"),
    ):
        owner_payload = event(body)
        owner_payload["issue"] = {"number": issue_number}
        assert admit(owner_payload).status == "accepted", body
        service_payload = event(body, actor=SERVICE_ACTOR)
        service_payload["issue"] = {"number": issue_number}
        result = admit_service(service_payload)
        assert (result.status, result.reason) == ("blocked", "actor-not-allowed"), body


def test_service_actor_malformed_validate_draft_is_rejected() -> None:
    for body in (
        "/agent-os validate-draft 2411 " + "a" * 39,  # short SHA
        "/agent-os validate-draft 2411 " + "A" * 40,  # uppercase SHA
        "/agent-os validate-draft 0 " + HEAD_SHA,  # PR number may not be zero
        "/agent-os validate-draft " + HEAD_SHA,  # missing PR number
        TRIGGER + " extra",  # trailing tokens
        TRIGGER + "; rm -rf /",  # shell syntax never reaches a shell
    ):
        result = admit_service(event(body, actor=SERVICE_ACTOR))
        assert (result.status, result.reason) == ("ignored", "malformed-trigger"), body
        assert result.draft_validation_pr_number_or_none is None


def test_service_actor_bare_prefix_is_not_a_command() -> None:
    result = admit_service(event("/agent-os validate-draft", actor=SERVICE_ACTOR))
    assert (result.status, result.reason) == ("blocked", "actor-not-allowed")


def test_service_actor_sender_must_match() -> None:
    payload = event(TRIGGER, actor=SERVICE_ACTOR)
    payload["sender"] = {"login": ACTOR}
    result = admit_service(payload)
    assert (result.status, result.reason) == ("blocked", "actor-evidence-mismatch")


def test_service_actor_pull_request_comment_is_ignored() -> None:
    payload = event(TRIGGER, actor=SERVICE_ACTOR)
    payload["issue"] = {"number": 2410, "pull_request": {"url": "https://example.invalid"}}
    result = admit_service(payload)
    assert (result.status, result.reason) == ("ignored", "pull-request-comment")


def test_service_actor_wrong_repository_is_blocked() -> None:
    payload = event(TRIGGER, actor=SERVICE_ACTOR)
    payload["repository"] = {"full_name": "mallory/agent-os"}
    result = admit_service(payload)
    assert (result.status, result.reason) == ("blocked", "repository-mismatch")


def test_service_actor_rerun_is_blocked() -> None:
    result = admit_service(event(TRIGGER, actor=SERVICE_ACTOR), run_attempt=2)
    assert (result.status, result.reason) == ("blocked", "workflow-rerun")


def test_service_actor_trigger_id_matches_owner_trigger_id() -> None:
    # Duplicate detection keys on the logical trigger, not the actor: an owner
    # command and a service-agent command for the same PR head are one trigger.
    owner = admit(event(TRIGGER))
    service = admit_service(event(TRIGGER, actor=SERVICE_ACTOR))
    assert service.logical_trigger_id_or_none == owner.logical_trigger_id_or_none


class _FakeDispatchClient:
    def __init__(self) -> None:
        self.dispatch_calls: list[dict] = []
        self._pages = [
            [],
            [
                WorkflowRunSummary(
                    run_id=909,
                    url="https://github.com/Blummer92/agent-os/actions/runs/909",
                    head_sha=HEAD_SHA,
                    created_at=datetime(2026, 10, 23, 12, 0, 5, tzinfo=timezone.utc),
                    status="completed",
                    conclusion="success",
                )
            ],
        ]

    def get_pull_request(self, pr_number: int) -> PullRequestState:
        return PullRequestState(
            state="open",
            draft=True,
            base_ref="main",
            head_ref="agent/2411-example",
            head_sha=HEAD_SHA,
            head_repo_full_name=REPOSITORY,
        )

    def list_validation_dispatch_runs(self, *, head_ref: str):
        return self._pages.pop(0) if self._pages else []

    def create_validation_dispatch(self, *, ref: str, pr_number: int, expected_head_sha: str) -> None:
        self.dispatch_calls.append(
            {"ref": ref, "pr_number": pr_number, "expected_head_sha": expected_head_sha}
        )


def test_service_actor_transport_drives_exactly_one_bounded_dispatch() -> None:
    transport = admit_service(event(TRIGGER, actor=SERVICE_ACTOR)).to_dict()
    client = _FakeDispatchClient()
    receipt = execute_dispatch(
        transport,
        client,
        dispatched_at=datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc),
        sleeper=lambda _seconds: None,
    )
    assert receipt["decision"] == "dispatched"
    assert receipt["actor"] == SERVICE_ACTOR
    assert receipt["run_id_or_none"] == 909
    assert receipt["observed_head_sha"] == HEAD_SHA
    assert receipt["validation_executed"] is False
    assert client.dispatch_calls == [
        {"ref": "agent/2411-example", "pr_number": 2411, "expected_head_sha": HEAD_SHA}
    ]
