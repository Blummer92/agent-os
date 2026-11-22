"""CKR PR-2: CKR5 future_use_hints survive to the reviewable catalog-draft
boundary as proposed, non-authoritative applicability hints.

The hints travel on the lesson proposal only. They never enter
``catalog_entry_draft`` properties (the Notion-bound surface), never become
verified applicability evidence, and never change Status or
Surface Before Work governance.
"""

from __future__ import annotations

import copy
import io
import json
import urllib.request

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge


def candidate(**changes):
    value = {
        "source_reference": "PR #3392 repair",
        "signal": "repeated-repair",
        "failure_signature": "issue-creation-path-skips-label-plan",
        "ecosystem": "agent-os",
        "capability_kind": "failure-avoidance",
        "lesson_summary": "Every issue-creation path must consume the canonical label plan",
        "what_happened": "Two repairs failed because one host creation path skipped the label plan.",
        "severity": "High",
        "owner_agent": "github-service-agent",
        "canonical_github_refs": ["https://github.com/Blummer92/agent-os/issues/3092"],
        "evidence_refs": ["https://github.com/Blummer92/agent-os/pull/3421"],
        "what_to_do_next_time": "Route every creation path through the label plan and read labels back.",
        "guardrail": "Terminal success requires label convergence by readback.",
        "reusable_rule_proven": True,
        "future_use_hints": ["label plan", "issue creation"],
    }
    value.update(changes)
    return value


def capture(monkeypatch, **changes):
    monkeypatch.setattr(
        bridge,
        "resolve_lesson_read_route",
        lambda: (_ for _ in ()).throw(AssertionError("capture must not read")),
    )
    envelope = bridge.parse_envelope({
        "operation": "lesson-candidate",
        "repository": "Blummer92/agent-os",
        "issue_number": 3418,
        "task_reference": "issue:#3418",
        "candidate": candidate(**changes),
    })
    assert bridge.classify_envelope(envelope)["retrieval_required"] is False
    return bridge.execute_envelope(envelope, retrieval_required=False)


def test_capture_proposal_carries_proposed_applicability_hints(monkeypatch):
    result = capture(monkeypatch)
    assert result["status"] == "reusable-new"
    proposal = result["lesson_proposal"]
    assert proposal["proposed_applicability_hints"] == ["issue creation", "label plan"]
    # Hints are proposals only: nothing about authority changes.
    assert proposal["authority_created"] is False
    assert proposal["notion_write_performed"] is False
    assert proposal["publication_authorized"] is False


def test_capture_hints_never_enter_catalog_entry_draft_properties(monkeypatch):
    result = capture(monkeypatch)
    draft = result["lesson_proposal"]["catalog_entry_draft"]
    assert "proposed_applicability_hints" not in draft["properties"]
    assert "future_use_hints" not in draft["properties"]
    assert set(draft["properties"]) == {
        "Lesson Learned",
        "What Happened",
        "What To Do Next Time",
        "Guardrail",
        "Learning Type",
        "Source Link",
    }
    assert {"Status", "Surface Before Work?"}.isdisjoint(draft["properties"])


def test_capture_without_hints_carries_empty_proposals(monkeypatch):
    result = capture(monkeypatch, future_use_hints=[])
    proposal = result["lesson_proposal"]
    assert proposal["proposed_applicability_hints"] == []
    # No hints means no surface-before-work recommendation (CKR5 rule).
    assert proposal["surface_before_work_recommendation"] is False


def test_capture_hints_do_not_become_verified_evidence(monkeypatch):
    # The proposal carries no applicability record, no reviewed mechanism,
    # and no verified observation: hints alone prove nothing.
    result = capture(monkeypatch)
    proposal = result["lesson_proposal"]
    assert "applicability_record" not in proposal
    assert "verified_mechanism" not in proposal
    assert proposal["proposed_applicability_hints"] == ["issue creation", "label plan"]


def _capture_event(**changes):
    payload = {
        "operation": "lesson-candidate",
        "repository": "Blummer92/agent-os",
        "issue_number": 3418,
        "task_reference": "issue:#3418",
        "candidate": candidate(**changes),
    }
    body = bridge.COMMAND_PREFIX + json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return {
        "repository": {"full_name": payload["repository"]},
        "issue": {"number": payload["issue_number"]},
        "comment": {"id": 1234, "user": {"login": "fixture-owner"}, "body": body},
    }


def _mock_postback(monkeypatch):
    posted_bodies = []

    def post(request, *, timeout):
        assert request.get_method() == "POST"
        posted_bodies.append(json.loads(request.data)["body"])
        return io.BytesIO(b'{"id":1235}')

    monkeypatch.setattr(bridge, "_existing_result_comment", lambda *args: None)
    monkeypatch.setattr(urllib.request, "urlopen", post)
    return posted_bodies


def _request_postback(event, result):
    return bridge.postback_result_comment(
        event=event,
        repository="Blummer92/agent-os",
        result=result,
        api_url="https://api.github.com",
        token="fixture",
    )


def _postback(monkeypatch, event, result):
    posted_bodies = _mock_postback(monkeypatch)
    receipt = _request_postback(event, result)
    assert receipt["posted_comment_id"] == 1235
    assert len(posted_bodies) == 1
    body = posted_bodies[0]
    assert len(body.encode("utf-8")) <= bridge.MAX_RESULT_COMMENT_BYTES
    return bridge.parse_ckr6_result_comment(body)


def test_capture_hints_are_posted_intact_when_the_result_fits(monkeypatch):
    result = capture(monkeypatch)
    payload = _postback(monkeypatch, _capture_event(), result)
    assert payload == {**result, "request_comment_id": 1234}


def test_capture_postback_keeps_catalog_draft_when_full_hints_exceed_wire_budget(monkeypatch):
    def text_at_limit(index, length):
        return (f"{index:02d} " + "Candidate notes and references for reusable CI work. " * 12)[:length]

    hints = [text_at_limit(index, 512) for index in range(20)]
    evidence_prefix = "https://github.com/Blummer92/agent-os/pull/3421#"
    event = _capture_event(
        future_use_hints=hints,
        lesson_summary=text_at_limit(1, 350),
        what_happened=text_at_limit(2, 512),
        what_to_do_next_time=text_at_limit(3, 512),
        guardrail=text_at_limit(4, 512),
        evidence_refs=[
            evidence_prefix + text_at_limit(index, 512 - len(evidence_prefix)).replace(" ", "-")
            for index in range(5)
        ],
    )
    assert len(event["comment"]["body"].encode("utf-8")) <= bridge.MAX_COMMENT_BYTES
    envelope = bridge.envelope_from_event(
        event, expected_repository="Blummer92/agent-os", allowed_actor="fixture-owner"
    )
    result = bridge.execute_envelope(envelope, retrieval_required=False)
    assert result["status"] == "reusable-new"
    assert result["lesson_proposal"]["proposed_applicability_hints"] == hints
    original_result = copy.deepcopy(result)
    with pytest.raises(ValueError, match="exceeds the bounded comment size"):
        bridge.serialize_ckr6_result_comment(result, request_comment_id=1234)

    payload = _postback(monkeypatch, event, result)
    expected = copy.deepcopy(original_result)
    del expected["lesson_proposal"]["proposed_applicability_hints"]
    expected["reason_codes"].append("proposed-applicability-hints-omitted-from-comment")
    assert payload == {**expected, "request_comment_id": 1234}
    assert result == original_result


def test_capture_postback_does_not_remove_existing_oversized_draft_fields(monkeypatch):
    result = capture(monkeypatch)
    result["lesson_proposal"]["catalog_entry_draft"]["properties"]["What Happened"] = (
        "x" * bridge.MAX_RESULT_COMMENT_BYTES
    )
    posted_bodies = _mock_postback(monkeypatch)
    with pytest.raises(ValueError, match="exceeds the bounded comment size"):
        _request_postback(_capture_event(), result)
    assert posted_bodies == []
