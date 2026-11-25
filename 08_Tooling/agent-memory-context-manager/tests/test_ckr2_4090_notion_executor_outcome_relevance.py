"""PR #4090 selector regression: Notion-read executor-outcome mechanism match.

A correctly authored lesson about rejecting explicit failed Notion executor
outcomes must be selectable by an explicit mechanism request, without the
generic "notion"/"quality-assurance" keywords doing the work and without the
new branch leaking onto unrelated tasks.
"""
from dataclasses import replace

import pytest

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest,
    SufficiencyStatus,
    select_coding_knowledge,
)
from agent_memory_context_manager.lesson_activation_bridge import (
    LessonActivationSkip,
    _as_selection_candidate,
    normalize_lesson_row,
)

REASON = "verified-notion-executor-outcome-match"

TITLE = "Reject failed executor outcomes before completing a Notion read"
GUIDANCE = (
    "Before marking governed read dispatch completed, validate executor output "
    "is a mapping and reject an explicit non-success status or non-null error. "
    "Test failed-status, error-despite-success, wrong-type and success controls "
    "on each route."
)
GUARDRAIL = (
    "Never infer execution success from a returned helper value or transport "
    "success alone. Project explicit failures into bounded sanitized receipts, "
    "keep curriculum state separate from execution completion, and do not treat "
    "passing CI as proof of live runtime acceptance."
)
REVISION = "2026-11-25T12:00:00.000Z"


def row(*, title=TITLE, guidance=GUIDANCE):
    def rich(value, kind="rich_text"):
        return {"type": kind, kind: [{"plain_text": value}]}

    def selected(value):
        return {"type": "select", "select": {"name": value}}

    return {
        "object": "page", "id": "fixture-4090", "last_edited_time": REVISION,
        "properties": {
            "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": 4090}},
            "Lesson Learned": rich(title, "title"),
            "Status": selected("New"),
            "Surface Before Work?": {"type": "checkbox", "checkbox": True},
            "Area": selected("Governance"),
            "Learning Type": selected("QA feedback"),
            "Applies To": {
                "type": "multi_select",
                "multi_select": [{"name": "Notion"}],
            },
            "Source Link": {"type": "url", "url": "https://github.com/Blummer92/agent-os/issues/2816"},
            "What To Do Next Time": rich(guidance),
            "Guardrail": rich(GUARDRAIL),
        },
    }


def candidate(**overrides):
    normalized = normalize_lesson_row(row(**overrides))
    assert not isinstance(normalized, LessonActivationSkip)
    return _as_selection_candidate(normalized)


def request(*hints: str, task: str = "reviewed task", paths=()):
    return CodingKnowledgeRequest(
        task_reference=task,
        ecosystem_hints=("agent-os",),
        language_hints=("Python",),
        capability_keywords=tuple(hints),
        target_path_hints=tuple(paths),
        specialized_knowledge_required=True,
    )


def reasons_for(req, cand):
    result = select_coding_knowledge(req, (cand,))
    selected = [item.reason_codes for item in result.selected]
    return result, selected


def test_explicit_mechanism_request_selects_via_contextual_reason():
    result, selected = reasons_for(
        request(
            "notion read", "executor outcome",
            task="The governed Notion read runner must reject an explicit failed "
                 "status returned by the executor before marking dispatch completed",
            paths=("scripts/agent_os_notion_read_request/runner.py",),
        ),
        candidate(),
    )
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert selected == [(REASON,)]


def test_extra_caller_hints_do_not_dilute_the_mechanism_match():
    _, selected = reasons_for(
        request("notion read", "executor outcome", "failure-receipts"),
        candidate(),
    )
    assert selected == [(REASON,)]


@pytest.mark.parametrize("hints", [
    ("notion read",),
    ("executor outcome",),
    ("notion", "executor"),
])
def test_partial_caller_signals_never_activate_the_branch(hints):
    _, selected = reasons_for(request(*hints), candidate())
    assert all(REASON not in reason_codes for reason_codes in selected)


def test_negated_title_never_activates_the_branch():
    _, selected = reasons_for(
        request("notion read", "executor outcome"),
        candidate(title="Do not reject failed executor outcomes before completing a Notion read"),
    )
    assert all(REASON not in reason_codes for reason_codes in selected)


def test_negated_guidance_never_activates_the_branch():
    _, selected = reasons_for(
        request("notion read", "executor outcome"),
        candidate(
            guidance="Do not validate executor output for an explicit failure "
                     "before marking governed read dispatch completed.",
        ),
    )
    assert all(REASON not in reason_codes for reason_codes in selected)


def test_guidance_without_completion_signal_never_activates_the_branch():
    _, selected = reasons_for(
        request("notion read", "executor outcome"),
        candidate(guidance="Reject failed executor output and surface an explicit error receipt."),
    )
    assert all(REASON not in reason_codes for reason_codes in selected)


def test_guardrail_text_alone_never_supplies_positive_evidence():
    # The Guardrail entry mentions failure and completion, but positive
    # evidence must come from the title and the primary guidance entry.
    _, selected = reasons_for(
        request("notion read", "executor outcome"),
        candidate(guidance="Record the executor outcome and continue the read."),
    )
    assert all(REASON not in reason_codes for reason_codes in selected)


HARD_NEGATIVES = (
    ("Publish a reviewed Lessons Learned entry through the governed writer and verify canonical Notion readback",
     ("notion", "lessons-write")),
    ("Discover available Notion databases and enumerate their schema properties",
     ("notion", "database-discovery")),
    ("Troubleshoot why the CKR6 mutation boundary gate did not revalidate after a trusted result postback",
     ("ckr6 mutation boundary",)),
    ("Fix CI packaging of transport artifacts for the validation workflow",
     ("ci", "packaging")),
    ("A Notion read executor returned success with a valid bounded payload; project the read evidence",
     ("notion",)),
)


@pytest.mark.parametrize("task,hints", HARD_NEGATIVES)
def test_unrelated_tasks_never_receive_the_contextual_reason(task, hints):
    _, selected = reasons_for(request(*hints, task=task), candidate())
    assert all(REASON not in reason_codes for reason_codes in selected)


_MECHANISM_TASKS = (
    "Reject explicit executor failure on a governed page read.",
    "An HTTP-success wrapper contains an unsuccessful execution result.",
    "A successful response carries a non-null error.",
    "A fetch helper returned a list rather than a result mapping.",
    "A returned helper value was mistaken for a completed dispatch.",
    "Do not mark a failed retrieval worker result as finished.",
)


def _snapshot():
    unrelated = (
        ("Verify canonical Notion writer persistence", "Re-read the written page and compare its fields.", "Notion"),
        ("Inspect Notion database metadata", "Confirm the schema before using a bounded query.", "Notion"),
        ("Verify release artifact identity", "Confirm the recorded SHA and checksum before release.", "Deployment"),
        ("Keep cache fixtures isolated", "Assert that each test uses its own temporary cache.", "Drive"),
    )
    records = []
    for i in range(1, 89):
        title, guidance, keyword = unrelated[(i - 1) % len(unrelated)]
        record = row(title=title, guidance=guidance)
        record["id"] = f"snapshot-page-{i}"
        props = record["properties"]
        props["Applies To"]["multi_select"] = [{"name": keyword}]
        props["Area"]["select"]["name"] = "Testing"
        props["Lesson ID"]["unique_id"]["number"] = i
        records.append(record)
    return [*records, row()]


def _snapshot_reader(records, boundaries, *, fault=None):
    stops = (0, *boundaries, len(records))
    calls = []

    def read(query):
        n = len(calls)
        assert n < len(stops) - 1, "unexpected second retrieval or cursor replay"
        calls.append(query.get("start_cursor"))
        assert calls[-1] == (None if n == 0 else f"opaque-page-{n}")
        has_more = n < len(stops) - 2
        return {
            "results": records[stops[n]:stops[n + 1]],
            "has_more": has_more or fault is not None,
            "next_cursor": (
                f"opaque-page-{n + 1}" if has_more
                else "opaque-page-1" if fault == "repeated"
                else None
            ),
        }

    return read, calls


def _retrieve(read, *, task=_MECHANISM_TASKS[0], hints=("notion read", "executor outcome"), languages=()):
    from agent_memory_context_manager.lesson_retrieval_orchestrator import orchestrate_lesson_retrieval

    req = replace(request(*hints, task=task), language_hints=languages)
    return orchestrate_lesson_retrieval(req, execute_read=read)


@pytest.mark.parametrize("boundaries", [(11, 37, 67), (1, 25, 48, 87)])
@pytest.mark.parametrize("task", _MECHANISM_TASKS)
def test_complete_snapshot_selects_late_contextual_lesson_without_id(boundaries, task):
    from agent_memory_context_manager.lesson_preflight import LessonRetrievalStatus

    read, calls = _snapshot_reader(_snapshot(), boundaries)
    # The extra keyword ranks multiple unrelated rows in a lower bucket.
    result = _retrieve(read, task=task, hints=("notion read", "executor outcome", "deployment"))
    assert len(calls) == len(boundaries) + 1
    assert result.retrieval_diagnostics["observed_rows"] == 89
    assert result.retrieval_diagnostics["normalized_rows"] == 89
    assert result.retrieval_diagnostics["skipped_rows"] == 0
    assert result.retrieval_diagnostics["best_bucket_tied_identities"] == 1
    assert result.candidate_count == 5
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-4090",)
    selected, = result.selection.selected
    assert selected.reason_codes == (REASON,)
    assert selected.candidate.source_revision == REVISION
    assert selected.candidate.canonical_github_refs == ("https://github.com/Blummer92/agent-os/issues/2816",)
    assert result.retrieval_diagnostics["selection_basis"] == "generic-unique"
    assert not (result.authority_created or result.notion_write_performed or result.github_write_performed)


@pytest.mark.parametrize("fault", ["repeated", "missing"])
def test_partial_snapshot_never_evaluates_even_when_match_was_read(fault):
    records = _snapshot()
    records.insert(0, records.pop())
    read, calls = _snapshot_reader(records[:32], (16,), fault=fault)
    result = _retrieve(read)
    assert calls == [None, "opaque-page-1"]
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics["selection_basis"] == "not-evaluated"
    assert result.retrieval_diagnostics["observed_rows"] == 0


@pytest.mark.parametrize("defect", ["conflicting-revision", "missing-revision", "missing-provenance"])
def test_snapshot_rejects_invalid_late_evidence(defect):
    records = _snapshot()
    if defect == "conflicting-revision":
        duplicate = row()
        duplicate["last_edited_time"] = "2026-11-24T12:00:00.000Z"
        records[0] = duplicate
    elif defect == "missing-revision":
        del records[-1]["last_edited_time"]
    else:
        records[-1]["properties"]["Source Link"]["url"] = None
    read, _ = _snapshot_reader(records, (20, 60))
    result = _retrieve(read)
    assert result.selected_lesson_ids == ()
    assert result.lesson_retrieval_status.value != "sufficient"
    if defect == "conflicting-revision":
        assert "duplicate-identity-conflict" in result.selection_reason_codes
    elif defect == "missing-revision":
        assert result.retrieval_diagnostics["missing_revision_rows"] == 1
    else:
        assert "unverifiable-relevant-candidate" in result.selection_reason_codes


@pytest.mark.parametrize("title", [
    "Skip rejecting failed executor outcomes before completing a Notion read",
    "Cannot reject failed executor outcomes before completing a Notion read",
    "Don't reject failed executor outcomes before completing a Notion read",
    "Don’t reject failed executor outcomes before completing a Notion read",
    "No need to reject failed executor outcomes before completing a Notion read",
])
def test_additional_negative_title_polarity(title):
    _, selected = reasons_for(request("notion read", "executor outcome"), candidate(title=title))
    assert all(REASON not in reason_codes for reason_codes in selected)



def test_unrelated_complete_snapshot_reports_no_signal():
    read, _ = _snapshot_reader(_snapshot(), (23, 74))
    result = _retrieve(read, task="Fix leap-day display in a calendar", hints=("calendar formatting",))
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics["normalized_rows"] == 89
    assert result.retrieval_diagnostics["selection_basis"] == "no-relevant-signal"


def test_new_reason_preserves_manual_review_for_broad_best_bucket_tie():
    read, _ = _snapshot_reader(_snapshot(), (23, 74))
    result = _retrieve(read, hints=("notion read", "executor outcome", "deployment"), languages=("Python",))
    assert result.retrieval_diagnostics["best_bucket_tied_identities"] > 5
    assert result.retrieval_diagnostics["selection_basis"] == "generic-tie-lexical-cut"
    assert result.selection_reason_codes == ("generic-relevance-unverified",)
    assert result.selected_lesson_ids == ()


def test_task_prose_alone_does_not_replace_typed_signals():
    read, _ = _snapshot_reader(_snapshot(), (23, 74))
    result = _retrieve(read, task="Reject a failed executor outcome before completing a Notion read", hints=())
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics["selection_basis"] == "no-relevant-signal"


@pytest.mark.parametrize("title,guidance", [
    ("Reject failed helper results before completing a Notion read", GUIDANCE),
    ("Reject failed executor outcomes before completing a calendar read", GUIDANCE),
    (TITLE, "Validate the executor output before dispatch completion."),
    (TITLE, "Unrelated guidance: reject the failure before dispatch completion."),
    (TITLE, "Don't check failure before marking dispatch completed."),
    (TITLE, "We don’t check failure before marking dispatch completed."),
])
def test_contextual_match_requires_independent_lesson_owned_signals(title, guidance):
    _, selected = reasons_for(
        request("notion read", "executor outcome"), candidate(title=title, guidance=guidance),
    )
    assert all(REASON not in reason_codes for reason_codes in selected)


@pytest.mark.parametrize("task,hints", [
    ("Persist an approved Notion lesson", ("Notion Writer", "persistence")),
    ("Verify the current revision of a Notion page by reading it back", ("notion read", "readback")),
    ("Add generic Notion integration telemetry", ("notion", "quality-assurance")),
    ("Audit unrelated fixture isolation", ("quality-assurance", "cache")),
])
def test_additional_hard_negatives_do_not_receive_notion_executor_reason(task, hints):
    _, selected = reasons_for(request(*hints, task=task), candidate())
    assert all(REASON not in reason_codes for reason_codes in selected)
