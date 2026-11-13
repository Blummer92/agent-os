"""Regression tests: bounded known-ID CKR6 activation diagnostics.

Notion rows here are modeled; no live Notion writes or host admission.
"""
from __future__ import annotations

from copy import deepcopy

from agent_os_execution_service import lesson_learning_loop as loop
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
