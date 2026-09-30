"""Regression tests for Issue #2745: bounded Drive lookup for the
teacher-directed revision lane.

Failure mode reproduced: the teacher directs a bounded worksheet revision
("Update the worksheet to match that decision. Keep everything else the
same."); the host starts a Google Drive search for the target worksheet and
freezes indefinitely -- no completed artifact and no visible governed
blocker. These tests prove the repository contract terminates every lookup
in exactly one bounded disposition (completed resolution or explicit,
visible governed blocker) and never in a silent freeze.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from instructional_workflow_contracts import (  # noqa: E402
    DRIVE_LOOKUP_MAX_ATTEMPTS,
    BoundedLookupDisposition,
    BoundedLookupResult,
    resolve_revision_target,
    thaw_json,
)


def _handoff(result):
    return thaw_json(result.resumable_handoff)


class ScriptedDrive:
    """Injected host lookup client with scripted per-call behavior."""

    def __init__(self, search_script=(), metadata=None):
        self.search_script = list(search_script)
        self.metadata = dict(metadata or {})
        self.search_calls = []
        self.metadata_calls = []

    def search_files(self, query, page_size):
        self.search_calls.append((query, page_size))
        if not self.search_script:
            raise AssertionError("search_files called with no scripted behavior left")
        behavior = self.search_script.pop(0)
        if isinstance(behavior, BaseException):
            raise behavior
        return behavior

    def get_file_metadata(self, file_id):
        self.metadata_calls.append(file_id)
        if isinstance(self.metadata.get(file_id), BaseException):
            raise self.metadata[file_id]
        return self.metadata.get(file_id)


def _revision_sections():
    return (
        ["scavenger-hunt activity -> Same Object, Five Ways activity"],
        ["everything else unchanged"],
    )


def _resolve(client, **kwargs):
    changed, preserved = _revision_sections()
    return resolve_revision_target(
        client=client,
        changed_sections=changed,
        preserved_sections=preserved,
        **kwargs,
    )


def test_exact_drive_id_reuses_identity_without_broad_search():
    client = ScriptedDrive(metadata={"worksheet-id-1": {"id": "worksheet-id-1", "name": "Composition"}})
    result = _resolve(client, exact_drive_id="worksheet-id-1", title_hint="Photography Composition")
    assert result.disposition is BoundedLookupDisposition.RESOLVED
    assert result.file_id == "worksheet-id-1"
    assert client.search_calls == []  # exact identity is reused; no broad search
    assert client.metadata_calls == ["worksheet-id-1"]


def test_exact_drive_id_missing_fails_visibly_with_resumable_handoff():
    client = ScriptedDrive()
    result = _resolve(client, exact_drive_id="worksheet-id-1")
    assert result.disposition is BoundedLookupDisposition.NOT_FOUND
    assert "can't find" in result.user_visible_message or "couldn't find" in result.user_visible_message
    handoff = _handoff(result)
    assert handoff["teacher_revision_request"]["changed_sections"] == [
        "scavenger-hunt activity -> Same Object, Five Ways activity"
    ]
    assert handoff["teacher_revision_request"]["preserved_sections"] == ["everything else unchanged"]
    assert handoff["resume_instruction"]
    assert not any(handoff["authority"].values())


def test_single_scoped_match_resolves_and_continues_revision():
    client = ScriptedDrive(search_script=[[{"id": "doc-7", "name": "Photography Composition Worksheet", "mimeType": "application/vnd.google-apps.document"}]])
    result = _resolve(client, title_hint="Photography Composition")
    assert result.disposition is BoundedLookupDisposition.RESOLVED
    assert result.file_id == "doc-7"
    query, page_size = client.search_calls[0]
    assert "trashed = false" in query
    assert "application/vnd.google-apps.document" in query
    assert page_size <= 10


def test_ambiguous_matches_fail_visibly_with_minimal_clarification():
    client = ScriptedDrive(
        search_script=[
            [
                {"id": "doc-a", "name": "Photography Composition Worksheet"},
                {"id": "doc-b", "name": "Photography Composition Worksheet (copy)"},
            ]
        ]
    )
    result = _resolve(client, title_hint="Photography Composition")
    assert result.disposition is BoundedLookupDisposition.AMBIGUOUS
    assert len(result.candidates) == 2
    assert "Photography Composition Worksheet" in result.user_visible_message
    assert _handoff(result)["candidates"][0]["drive_file_id"] == "doc-a"


def test_zero_candidates_is_terminal_not_found_not_retry():
    client = ScriptedDrive(search_script=[[]])
    result = _resolve(client, title_hint="Photography Composition")
    assert result.disposition is BoundedLookupDisposition.NOT_FOUND
    assert len(client.search_calls) == 1  # zero results are terminal; no pointless retry
    assert result.user_visible_message  # visible governed blocker, not silence


def test_repeated_provider_failures_hit_attempt_cap_with_visible_blocker():
    client = ScriptedDrive(search_script=[RuntimeError("boom")] * DRIVE_LOOKUP_MAX_ATTEMPTS)
    result = _resolve(client, title_hint="Photography Composition")
    assert result.disposition is BoundedLookupDisposition.LOOKUP_ERROR
    assert len(client.search_calls) == DRIVE_LOOKUP_MAX_ATTEMPTS
    assert result.attempts_used == DRIVE_LOOKUP_MAX_ATTEMPTS
    assert "boom" in (result.failure_detail or "")
    assert result.user_visible_message  # teacher sees a blocker, never a freeze
    assert _handoff(result)["teacher_revision_request"]["changed_sections"]


def test_transient_failure_then_success_resolves_within_bounds():
    client = ScriptedDrive(
        search_script=[
            RuntimeError("transient"),
            [{"id": "doc-9", "name": "Photography Composition Worksheet"}],
        ]
    )
    result = _resolve(client, title_hint="Photography Composition")
    assert result.disposition is BoundedLookupDisposition.RESOLVED
    assert result.file_id == "doc-9"
    assert result.attempts_used == 2


def test_host_timeout_surfaces_as_lookup_timeout_blocker():
    client = ScriptedDrive(search_script=[TimeoutError("per-call timeout")] * DRIVE_LOOKUP_MAX_ATTEMPTS)
    result = _resolve(client, title_hint="Photography Composition")
    assert result.disposition is BoundedLookupDisposition.LOOKUP_TIMEOUT
    assert result.timed_out is True
    assert len(client.search_calls) == DRIVE_LOOKUP_MAX_ATTEMPTS
    assert "keep you waiting" in result.user_visible_message


def test_elapsed_budget_exhaustion_terminates_between_attempts():
    ticks = iter([0.0, 0.0, 61.0])  # one attempt, then the budget is gone
    client = ScriptedDrive(search_script=[RuntimeError("slow")])
    result = _resolve(client, title_hint="Photography Composition", clock=lambda: next(ticks, 61.0))
    assert result.disposition is BoundedLookupDisposition.LOOKUP_TIMEOUT
    assert result.timed_out is True
    assert len(client.search_calls) == 1  # budget checked before a second attempt


def test_oversized_title_hint_rejected_before_any_provider_call():
    client = ScriptedDrive(search_script=[[]])
    result = _resolve(client, title_hint="x" * 500)
    assert result.disposition is BoundedLookupDisposition.LOOKUP_ERROR
    assert client.search_calls == []
    assert result.user_visible_message


def test_missing_client_fails_visibly_without_hang():
    result = _resolve(None, title_hint="Photography Composition")
    assert result.disposition is BoundedLookupDisposition.LOOKUP_ERROR
    assert result.user_visible_message


def test_missing_target_identity_fails_visibly():
    client = ScriptedDrive()
    result = _resolve(client)
    assert result.disposition is BoundedLookupDisposition.LOOKUP_ERROR
    assert client.search_calls == [] and client.metadata_calls == []
    assert result.user_visible_message


def test_every_terminal_blocker_carries_message_and_handoff():
    blockers = [
        _resolve(ScriptedDrive(), exact_drive_id="missing-id"),
        _resolve(ScriptedDrive(search_script=[[]]), title_hint="Photography Composition"),
        _resolve(
            ScriptedDrive(
                search_script=[
                    [
                        {"id": "a", "name": "one"},
                        {"id": "b", "name": "two"},
                    ]
                ]
            ),
            title_hint="Photography Composition",
        ),
        _resolve(ScriptedDrive(search_script=[RuntimeError("x")] * 3), title_hint="Photography Composition"),
        _resolve(ScriptedDrive(search_script=[TimeoutError()] * 3), title_hint="Photography Composition"),
        _resolve(None, title_hint="Photography Composition"),
    ]
    seen = set()
    for result in blockers:
        assert isinstance(result, BoundedLookupResult)
        assert result.disposition in {
            BoundedLookupDisposition.AMBIGUOUS,
            BoundedLookupDisposition.NOT_FOUND,
            BoundedLookupDisposition.LOOKUP_TIMEOUT,
            BoundedLookupDisposition.LOOKUP_ERROR,
        }
        assert result.user_visible_message.strip(), "blocker must be visible, never silent"
        assert _handoff(result)["contract_version"] == "revision-target-drive-lookup-v1"
        seen.add(result.disposition)
    assert seen == {
        BoundedLookupDisposition.AMBIGUOUS,
        BoundedLookupDisposition.NOT_FOUND,
        BoundedLookupDisposition.LOOKUP_TIMEOUT,
        BoundedLookupDisposition.LOOKUP_ERROR,
    }


def test_bounds_cannot_be_widened_past_contract_maxima():
    client = ScriptedDrive()
    with pytest.raises(Exception):
        _resolve(client, title_hint="x", max_attempts=DRIVE_LOOKUP_MAX_ATTEMPTS + 1)
    with pytest.raises(Exception):
        _resolve(client, title_hint="x", max_elapsed_seconds=9999.0)
