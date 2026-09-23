"""#2283 bounded notion-read transport admission and GCE-routing refusal.

These tests lock two properties:

1. ``/agent-os notion-read <request-id>`` is admitted only as a finite command
   shape carrying a repository-owned slug -- never a Notion id, URL, filter,
   property name, shell fragment, or free-form teacher text.
2. An accepted notion-read envelope can never reach the GCE control path, so the
   routine curriculum/Visual Asset Library read acquires no GCE dependency.
"""

from __future__ import annotations

import pytest

from workflow_scheduler.governance.github_issue_comment_ingress import (
    admit_issue_comment_event,
)

REPOSITORY = "Blummer92/agent-os"
ACTOR = "Blummer92"
REQUEST_ID = "photography-foundations-visual-assets"
TRIGGER = f"/agent-os notion-read {REQUEST_ID}"


def event(
    body: str, *, action: str = "created", actor: str = ACTOR, sender: str | None = None
) -> dict[str, object]:
    return {
        "action": action,
        "repository": {"full_name": REPOSITORY},
        "issue": {"number": 2283},
        "comment": {"id": 991, "body": body, "user": {"login": actor}},
        "sender": {"login": sender or actor},
    }


def admit(payload: object, *, run_attempt: int = 1):
    return admit_issue_comment_event(
        payload,
        expected_repository=REPOSITORY,
        allowed_actor=ACTOR,
        run_attempt=run_attempt,
    )


def test_trusted_canonical_notion_read_request_is_accepted() -> None:
    result = admit(event(TRIGGER))

    assert result.status == "accepted"
    assert result.reason == "accepted-notion-read-envelope"
    assert result.notion_read_request_id_or_none == REQUEST_ID
    assert result.handoff_id_or_none is None
    assert result.logical_trigger_id_or_none is not None
    # Transport admission never becomes execution authority.
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False
    assert result.to_dict()["notion_read_request_id_or_none"] == REQUEST_ID


def test_notion_read_logical_trigger_is_distinct_per_request() -> None:
    first = admit(event(TRIGGER)).logical_trigger_id_or_none
    second = admit(event("/agent-os notion-read photography-foundations-canonical-unit"))

    assert first != second.logical_trigger_id_or_none


def test_untrusted_actor_cannot_request_a_notion_read() -> None:
    result = admit(event(TRIGGER, actor="someone-else"))

    assert result.status == "blocked"
    assert result.reason == "actor-not-allowed"
    assert result.notion_read_request_id_or_none is None


def test_spoofed_sender_cannot_request_a_notion_read() -> None:
    result = admit(event(TRIGGER, sender="someone-else"))

    assert result.status == "blocked"
    assert result.reason == "actor-evidence-mismatch"


def test_wrong_repository_fails_closed() -> None:
    payload = event(TRIGGER)
    payload["repository"] = {"full_name": "someone/else"}

    result = admit(payload)

    assert result.status == "blocked"
    assert result.reason == "repository-mismatch"


def test_wrong_event_action_fails_closed() -> None:
    result = admit(event(TRIGGER, action="edited"))

    assert result.status == "blocked"
    assert result.reason == "event-not-created"


def test_pull_request_comment_is_ignored() -> None:
    payload = event(TRIGGER)
    payload["issue"] = {"number": 2283, "pull_request": {"url": "https://example.invalid"}}

    result = admit(payload)

    assert result.status == "ignored"
    assert result.reason == "pull-request-comment"


def test_workflow_rerun_replay_fails_closed() -> None:
    result = admit(event(TRIGGER), run_attempt=2)

    assert result.status == "blocked"
    assert result.reason == "workflow-rerun"


@pytest.mark.parametrize(
    "body",
    [
        # Arbitrary Notion identities and URLs.
        "/agent-os notion-read da5cba48-50fd-4377-9790-8df8f6f2c7dd",
        "/agent-os notion-read https://www.notion.so/some-private-page",
        # Arbitrary shell syntax and command chaining.
        "/agent-os notion-read visual-assets; cat /etc/passwd",
        "/agent-os notion-read visual-assets && env",
        "/agent-os notion-read $(printenv NOTION_TOKEN)",
        "/agent-os notion-read `id`",
        "/agent-os notion-read visual-assets | tee /tmp/out",
        # Arbitrary API paths, property names, and filters.
        "/agent-os notion-read /v1/databases/abc/query",
        "/agent-os notion-read visual-assets --property Title",
        '/agent-os notion-read {"filter":{"property":"Title"}}',
        # Workspace-wide search and write verbs.
        # A well-formed-but-unregistered slug such as `search` is deliberately not
        # listed here: the transport parser holds no repository state, so unknown
        # request identities fail closed at catalog admission instead. See
        # tests/agent_os_notion_read_request/test_admission.py.
        "/agent-os notion-read *",
        "/agent-os notion-read visual-assets --method PATCH",
        # Extra executable tokens and free-form teacher text.
        "/agent-os notion-read visual-assets extra-token",
        "/agent-os notion-read show me the photography images please",
        # Malformed slug shapes.
        "/agent-os notion-read -leading-hyphen",
        "/agent-os notion-read trailing-hyphen-",
        "/agent-os notion-read double--hyphen",
        "/agent-os notion-read ab",
        "/agent-os notion-read UPPERCASE",
        "/agent-os notion-read with_underscore",
        "/agent-os notion-read " + "a" * 64,
        # Prefix/suffix smuggling around the canonical command.
        f"please {TRIGGER}",
        f"{TRIGGER}\nrm -rf /",
        "/agent-os notion-read",
        "/agent-os notion-read ",
    ],
)
def test_malformed_or_arbitrary_notion_read_commands_fail_closed(body: str) -> None:
    result = admit(event(body))

    assert result.status != "accepted"
    assert result.notion_read_request_id_or_none is None


def test_oversized_comment_fails_closed_before_parsing() -> None:
    result = admit(event(TRIGGER + " " + "x" * 300))

    assert result.status == "ignored"
    assert result.reason == "malformed-trigger"


def test_accepted_notion_read_envelope_is_never_routed_to_gce() -> None:
    """The notion-read branch must refuse GCE routing without touching the host."""
    from workflow_scheduler.governance import gce_gcloud_adapter

    class ExplodingAdapter:
        def __getattr__(self, name: str):  # pragma: no cover - must never run
            raise AssertionError(f"GCE adapter must not be used for a notion read: {name}")

    ingress = admit(event(TRIGGER))
    evidence = gce_gcloud_adapter.execute_transport(
        ingress, claims={}, adapter=ExplodingAdapter()
    )

    assert set(evidence) == {"notion_read"}
    notion_read = evidence["notion_read"]
    assert notion_read["status"] == "blocked"
    assert notion_read["reason_codes"] == ["notion-read-not-gce-routable"]
    assert notion_read["request_id"] == REQUEST_ID
    assert notion_read["gce_invoked"] is False
    assert notion_read["execution_authorized"] is False
    assert notion_read["scheduler_invoked"] is False
    assert notion_read["side_effects_performed"] is False
    # No GCE binding or control result may be produced for this path.
    assert "binding" not in evidence
    assert "control" not in evidence
