"""Regression tests: bounded known-ID CKR6 activation diagnostics.

Notion rows here are modeled; no live Notion writes or host admission.
"""
from __future__ import annotations

from copy import deepcopy

from agent_os_execution_service import lesson_learning_loop as loop
from agent_os_execution_service import ckr6_github_bridge as bridge
from agent_os_execution_service.issue_start_lesson_preflight import (
    activate_issue_start_lesson_preflight,
)
from agent_memory_context_manager.lesson_preflight import MAX_LESSON_RECORDS

REVISION = "2026-10-08T12:00:00.000Z"


def _rt(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text}]}


def row(number=999, *, status="New", area="Governance", revision=REVISION):
    return {
        "object": "page", "last_edited_time": revision,
        "url": f"https://www.notion.so/{number}",
        "properties": {
            "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": number}},
            "Lesson Learned": {"type": "title", "title": [{"plain_text": "Verify labels after creation"}]},
            "Status": {"type": "select", "select": None if status is None else {"name": status}},
            "Surface Before Work?": {"type": "checkbox", "checkbox": True},
            "Area": {"type": "select", "select": None if area is None else {"name": area}},
            "Learning Type": {"type": "select", "select": {"name": "Mistake"}},
            "Applies To": {"type": "multi_select", "multi_select": [{"name": "Notion"}]},
            "Source Link": {"type": "url", "url": "https://github.com/Blummer92/agent-os/issues/3305"},
            "Guardrail": _rt("Verify the exact result and do not bypass checks."),
            "What To Do Next Time": _rt("Use canonical evidence before repair."),
        },
    }


def reader(rows):
    calls = []

    def execute_read(query):
        calls.append(deepcopy(query))
        return {"results": deepcopy(rows), "has_more": False}

    execute_read.calls = calls
    return execute_read


def run(rows, known=("LL-999",)):
    return activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os", issue_number=3418,
        task_reference="issue:#3418", specialized_knowledge_required=True,
        capability_keywords=("failure-avoidance",),
        known_knowledge_refs=known, execute_read=reader(rows),
    )


def test_status_skip_is_diagnosed_without_admission():
    result = run([row(status=None)])
    assert not result["selected_lesson_ids"]
    assert result["substantial_hypothesis_admissible"] is False
    assert result["rejected_candidate_provenance"] == [{
        "lesson_id": "LL-999", "source_revision": REVISION,
        "currentness": "not-activatable",
        "provenance": "normalization-skip:ambiguous-status-vocabulary",
    }]
    assert result["github_writes_authorized"] is False
    assert result["execution_authorized"] is False


def test_area_missing_after_owner_status_is_diagnosed():
    result = run([row(area=None)])
    assert result["rejected_candidate_provenance"][0]["provenance"] == (
        "normalization-skip:ambiguous-area-vocabulary"
    )
    assert result["selected_lesson_ids"] == []


def test_mixed_requested_valid_and_invalid_preserves_selection():
    result = run([row(), row(998, area=None)], ("LL-999", "LL-998"))
    assert result["selected_lesson_ids"] == ["LL-999"]
    assert result["lesson_retrieval_status"] == "sufficient"
    assert result["substantial_hypothesis_admissible"] is True
    assert result["rejected_candidate_provenance"][0]["lesson_id"] == "LL-998"


def test_unrequested_invalid_row_not_reported():
    result = run([row(), row(998, status=None)])
    assert result["selected_lesson_ids"] == ["LL-999"]
    assert result["rejected_candidate_provenance"] == []


def test_oversized_provider_response_does_not_leak_row_beyond_first_25():
    first_30 = [row(n, status=None) for n in range(1, 31)]
    result = run(first_30 + [row(999, status=None)])
    assert result["selected_lesson_ids"] == []
    assert result["rejected_candidate_provenance"] == []


def test_no_more_than_five_diagnostics():
    rows = [row(n, status=None) for n in range(990, 1005)]
    result = run(rows, tuple(f"LL-{n}" for n in range(990, 995)))
    evidence = result["rejected_candidate_provenance"]
    assert len(evidence) <= MAX_LESSON_RECORDS
    assert len({x["lesson_id"] for x in evidence}) == len(evidence)


def test_duplicate_row_is_reported_once():
    result = run([row(status=None), row(status=None)])
    assert len(result["rejected_candidate_provenance"]) == 1


def test_bad_revision_does_not_leak_raw_content():
    result = run([row(status=None, revision="bad\nprovider-secret")])
    assert result["rejected_candidate_provenance"][0]["source_revision"] == "unknown"


def test_no_read_on_not_needed():
    execute_read = reader([row(status=None)])
    result = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os", issue_number=3418,
        task_reference="issue:#3418", specialized_knowledge_required=False,
        known_knowledge_refs=("LL-999",), execute_read=execute_read,
    )
    assert result["lesson_retrieval_status"] == "not-needed"
    assert result["rejected_candidate_provenance"] == []
    assert execute_read.calls == []


def test_rejected_eligible_candidate_takes_provenance_precedence():
    unverifiable = row()
    unverifiable["properties"]["Source Link"]["url"] = None
    rows = [unverifiable] + [row(n, area=None) for n in (998, 997, 996, 995)]
    result = run(rows, ("LL-999", "LL-998", "LL-997", "LL-996", "LL-995"))
    evidence = result["rejected_candidate_provenance"]
    assert len(evidence) <= MAX_LESSON_RECORDS
    assert any(x["lesson_id"] == "LL-999" for x in evidence)


def test_capture_warns_reviewer_but_does_not_create_authority():
    candidate = {
        "source_reference": "PR #3392 repair", "signal": "repeated-repair",
        "failure_signature": "issue-creation-path-skips-label-plan",
        "ecosystem": "agent-os", "capability_kind": "failure-avoidance",
        "lesson_summary": "Every creation path must consume the canonical label plan",
        "what_happened": "Two repairs failed because creation skipped the label plan.",
        "severity": "High", "owner_agent": "github-service-agent",
        "canonical_github_refs": ["https://github.com/Blummer92/agent-os/issues/3092"],
        "evidence_refs": ["https://github.com/Blummer92/agent-os/pull/3421"],
        "what_to_do_next_time": "Use the label plan and read back the result.",
        "guardrail": "Terminal success requires label convergence by readback.",
        "reusable_rule_proven": True,
    }
    proposal = loop.capture_lesson_candidate(candidate)["lesson_proposal"]
    assert proposal["activation_gaps"] == ["Area"]
    assert proposal["owner_activation_required"] == ["Status", "Surface Before Work?"]
    assert proposal["catalog_ready"] is True
    assert "Status" not in proposal["catalog_entry_draft"]["properties"]
    assert "Surface Before Work?" not in proposal["catalog_entry_draft"]["properties"]


def test_modeled_capture_write_read_selection_seam():
    candidate = {
        "source_reference": "PR #3392 repair", "signal": "repeated-repair",
        "failure_signature": "issue-creation-path-skips-label-plan",
        "ecosystem": "agent-os", "capability_kind": "failure-avoidance",
        "lesson_summary": "Every creation path must consume the canonical label plan",
        "what_happened": "Two repairs failed because creation skipped the label plan.",
        "severity": "High", "owner_agent": "github-service-agent",
        "canonical_github_refs": ["https://github.com/Blummer92/agent-os/issues/3092"],
        "evidence_refs": ["https://github.com/Blummer92/agent-os/pull/3421"],
        "what_to_do_next_time": "Use the label plan and read back the result.",
        "guardrail": "Terminal success requires label convergence by readback.",
        "reusable_rule_proven": True,
    }
    draft = loop.capture_lesson_candidate(candidate)["lesson_proposal"]["catalog_entry_draft"]["properties"]
    page = row(1000, area=None)
    page["properties"]["Lesson Learned"]["title"][0]["plain_text"] = draft["Lesson Learned"]
    page["properties"]["Guardrail"] = _rt(draft["Guardrail"])
    page["properties"]["What To Do Next Time"] = _rt(draft["What To Do Next Time"])
    page["properties"]["Learning Type"]["select"] = {"name": draft["Learning Type"]}
    page["properties"]["Source Link"]["url"] = draft["Source Link"]
    missing = run([page], ("LL-1000",))
    assert missing["selected_lesson_ids"] == []
    assert missing["rejected_candidate_provenance"][0]["provenance"] == (
        "normalization-skip:ambiguous-area-vocabulary"
    )
    page["properties"]["Area"]["select"] = {"name": "Governance"}
    selected = run([page], ("LL-1000",))
    assert selected["selected_lesson_ids"] == ["LL-1000"]
    assert selected["rejected_candidate_provenance"] == []


def test_raw_provider_entries_bound_including_non_mapping_values():
    # The diagnostic observer must not inspect a valid 26th row after 25
    # malformed raw entries (even when the canonical parser filters them).
    oversized = [None] * 25 + [row(status=None)]
    result = run(oversized)
    assert result["selected_lesson_ids"] == []
    assert result["rejected_candidate_provenance"] == []


def test_sanitized_skip_survives_canonical_ckr6_result_comment():
    result = run([row(area=None)])
    envelope = {
        "operation": "issue-start",
        "rejected_candidate_provenance": result["rejected_candidate_provenance"],
        "selected_lesson_ids": result["selected_lesson_ids"],
        "substantial_hypothesis_admissible": result["substantial_hypothesis_admissible"],
    }
    body = bridge.serialize_ckr6_result_comment(envelope, request_comment_id=123)
    assert len(body.encode("utf-8")) <= bridge.MAX_RESULT_COMMENT_BYTES
    parsed = bridge.parse_ckr6_result_comment(body)
    assert parsed["rejected_candidate_provenance"] == result["rejected_candidate_provenance"]
    assert parsed["request_comment_id"] == 123
    assert "normalization-skip:ambiguous-area-vocabulary" in body


def test_ckr6_result_comment_size_limit_preserved():
    with __import__("pytest").raises(ValueError, match="bounded comment size"):
        bridge.serialize_ckr6_result_comment({
            "operation": "issue-start",
            "reason_codes": ["X" * bridge.MAX_RESULT_COMMENT_BYTES],
        }, request_comment_id=123)


def _run_insufficient(rows, known=()):
    """Eligible candidates rejected via unmatched capability keywords."""
    return activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os", issue_number=3418,
        task_reference="issue:#3418", specialized_knowledge_required=True,
        capability_keywords=("no-such-capability-xyz",),
        known_knowledge_refs=known, execute_read=reader(rows),
    )


def test_combined_rejections_and_skips_capped_at_five():
    rows = [row(1), row(2), row(3)] + [row(n, status=None) for n in range(10, 15)]
    result = _run_insufficient(rows, tuple(f"LL-{n}" for n in range(10, 15)))
    evidence = result["rejected_candidate_provenance"]
    assert len(evidence) == MAX_LESSON_RECORDS == 5
    assert [x["lesson_id"] for x in evidence] == ["LL-1", "LL-2", "LL-3", "LL-10", "LL-11"]


def test_eligible_rejections_precede_requested_skips_regardless_of_row_order():
    rows = [row(n, status=None) for n in range(10, 15)] + [row(1), row(2), row(3)]
    result = _run_insufficient(rows, tuple(f"LL-{n}" for n in range(10, 15)))
    evidence = result["rejected_candidate_provenance"]
    assert [x["provenance"] for x in evidence] == (
        ["canonical-github-ref-present"] * 3
        + ["normalization-skip:ambiguous-status-vocabulary"] * 2
    )


def _surface_unchecked(number=999):
    item = row(number)
    item["properties"]["Surface Before Work?"]["checkbox"] = False
    return item


def test_requested_surface_unchecked_is_diagnosed():
    result = run([_surface_unchecked()])
    assert result["selected_lesson_ids"] == []
    assert result["rejected_candidate_provenance"] == [{
        "lesson_id": "LL-999", "source_revision": REVISION,
        "currentness": "not-activatable",
        "provenance": "eligibility-skip:surface-before-work-unchecked",
    }]


def test_requested_archived_note_status_is_diagnosed():
    result = run([row(status="Archived note")])
    assert result["selected_lesson_ids"] == []
    assert result["rejected_candidate_provenance"][0]["provenance"] == (
        "eligibility-skip:archived-note-status"
    )


def test_disallowed_status_outside_vocabulary_stays_a_normalization_skip():
    # "Done" is outside the Status vocabulary, so normalization fails closed
    # before the eligibility rule; the eligibility status branch only covers
    # vocabulary statuses outside the allowed set (today: none beyond
    # "Archived note", which has its own reason and test above).
    result = run([row(status="Done")])
    assert result["selected_lesson_ids"] == []
    assert result["rejected_candidate_provenance"][0]["provenance"] == (
        "normalization-skip:ambiguous-status-vocabulary"
    )


def test_eligibility_skip_visible_when_another_requested_lesson_selected():
    result = run([row(), _surface_unchecked(998)], ("LL-999", "LL-998"))
    assert result["lesson_retrieval_status"] == "sufficient"
    assert result["selected_lesson_ids"] == ["LL-999"]
    assert result["rejected_candidate_provenance"][0] == {
        "lesson_id": "LL-998", "source_revision": REVISION,
        "currentness": "not-activatable",
        "provenance": "eligibility-skip:surface-before-work-unchecked",
    }
    assert result["substantial_hypothesis_admissible"] is True


def test_eligibility_and_normalization_skips_share_the_five_record_cap():
    rows = ([row(n, status=None) for n in (10, 11, 12)]
            + [_surface_unchecked(13), _surface_unchecked(14), row(15, status="Done")])
    result = run(rows, tuple(f"LL-{n}" for n in range(10, 16)))
    evidence = result["rejected_candidate_provenance"]
    assert len(evidence) == MAX_LESSON_RECORDS == 5
    assert [x["lesson_id"] for x in evidence] == ["LL-10", "LL-11", "LL-12", "LL-13", "LL-14"]
    assert evidence[3]["provenance"] == "eligibility-skip:surface-before-work-unchecked"


def test_eligible_requested_row_not_selected_gets_no_skip_record():
    result = run([row(), row(998)], ("LL-999", "LL-998"))
    assert result["lesson_retrieval_status"] == "sufficient"
    assert set(result["selected_lesson_ids"]) == {"LL-999", "LL-998"}
    assert result["rejected_candidate_provenance"] == []
