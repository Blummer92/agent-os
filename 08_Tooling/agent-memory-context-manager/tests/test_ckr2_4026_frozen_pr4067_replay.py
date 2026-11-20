"""#4026: reproduce the PR #4067 CKR6 33-way tie from a frozen, redacted pool.

These are failure characterization tests, not assertions that "sufficient"
means relevant. The 35-row projection of 87 observed Notion rows captures
the 33 bucket-2 identities and task-overlap signatures. No live network,
private Notion page IDs, full lesson narratives, or human gold labels.
Source archive SHA256: 2531aa74fc5d9a902e957d48765ca979b8aa382e4dddf3a3a201b32e9e943b60
Source data/lessons.json SHA256: 944a6baa963d4aa78607e023c78e0fae6b92a821651bf00b408454c5ed8116ae
Bot result: PR #4067 comment 7040605611; main 740bb83a.
"""
from pathlib import Path

import pytest

from agent_memory_context_manager import coding_knowledge_selection as cks
from agent_memory_context_manager import lesson_activation_bridge as bridge
from agent_memory_context_manager.lesson_preflight import LessonRetrievalStatus
from agent_memory_context_manager.lesson_retrieval_orchestrator import (
    orchestrate_lesson_retrieval,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ckr2_4026_33way_rank_signatures.tsv"
CORE = (
    "PR #4067 exact head 5346d30962f0ee0004ed5ab12f9d3dce4b253f57: "
    "validate tests-only CKR2 LL-51 unrelated packaging negative control, "
    "explicit mutation-boundary positive, provenance, pagination, "
    "and mutation-discrimination tests."
)
DISCLAIMER = "No merge, issue closure, or Notion write authorization."
AFFIRMATIVE = "Merge, issue closure, and Notion write are authorized."
REQUEST_TEXT = {
    "original": CORE + " " + DISCLAIMER,
    "without_disclaimer": CORE,
    "disclaimer_only": DISCLAIMER,
    "inverted_disclaimer": CORE + " " + AFFIRMATIVE,
}
SELECTED = {
    "original": ("LL-50", "LL-56", "LL-18"),
    "without_disclaimer": ("LL-18", "LL-55", "LL-50"),
    "disclaimer_only": ("LL-50", "LL-27", "LL-56"),
    "inverted_disclaimer": ("LL-50", "LL-56", "LL-18"),
}
# Canonical-shaped synthetic reference proves source-presence logic only.
# It does NOT represent verification of the actual lesson's GitHub source.
SYNTHETIC_REF = "https://github.com/Blummer92/agent-os/issues/4026"


def request(kind="original"):
    return cks.CodingKnowledgeRequest(
        task_reference=REQUEST_TEXT[kind],
        ecosystem_hints=("python",),
        capability_keywords=("testing", "lesson-selection"),
        specialized_knowledge_required=True,
    )


def rich(value, kind="rich_text"):
    return {"type": kind, kind: [{"plain_text": value}]}


def rows():
    result = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        ident, area, kind, status, source, revision, tokens, applies = line.split("|", 7)
        assert source in {"src", "missing"}
        assert all(token.isascii() for token in tokens.split())
        number = int(ident.split("-")[1])
        result.append({
            "object": "page",
            "id": f"redacted-{number}",
            "last_edited_time": revision,
            "properties": {
                "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": number}},
                "Lesson Learned": rich("Archived candidate signature", "title"),
                "Status": {"type": "select", "select": {"name": status}},
                "Surface Before Work?": {"type": "checkbox", "checkbox": True},
                "Area": {"type": "select", "select": {"name": area}},
                "Learning Type": {"type": "select", "select": {"name": kind}},
                "Applies To": {"type": "multi_select", "multi_select": [
                    {"name": value} for value in applies.split(",") if value
                ]},
                "Source Link": {"type": "url", "url": SYNTHETIC_REF if source == "src" else None},
                "Guardrail": rich("Masked guidance without extra request terms"),
                "What To Do Next Time": rich(tokens or "masked guidance"),
            },
        })
    return result


def candidates():
    values = [bridge.normalize_lesson_row(row) for row in rows()]
    assert all(isinstance(v, bridge.LessonRecordEvidence) for v in values)
    return values


def replay(kind="original", input_rows=None):
    result_rows = rows() if input_rows is None else input_rows
    return orchestrate_lesson_retrieval(
        request(kind),
        execute_read=lambda _q: {
            "results": list(result_rows),
            "has_more": False,
            "next_cursor": None,
        },
    )


def test_snapshot_has_33_way_bucket_two_tie_and_unverified_candidate():
    found = candidates()
    assert len(found) == len({r.lesson_id for r in found}) == 35
    by_id = {r.lesson_id: r for r in found}
    assert by_id["LL-84"].currentness is cks.KnowledgeCurrentness.UNVERIFIABLE
    bucket_two = [
        r for r in found
        if bridge._match_candidate(request(), bridge._as_selection_candidate(r))[0] == 2
    ]
    assert len(bucket_two) == 33
    assert bridge._match_candidate(
        request(), bridge._as_selection_candidate(by_id["LL-51"])
    )[0] == 0
    assert bridge._match_candidate(
        request(), bridge._as_selection_candidate(by_id["LL-86"])
    )[0] == 1


@pytest.mark.parametrize("kind", [
    "original", "without_disclaimer", "disclaimer_only", "inverted_disclaimer",
])
def test_frozen_production_retrieval_characterization(kind):
    # This pins a failure observed in 2026, not the behavior desired after repair.
    result = replay(kind)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == SELECTED[kind]
    assert result.selection_reason_codes == ("knowledge-sufficient",)
    if kind == "original":
        assert result.retrieval_diagnostics["best_bucket_tied_identities"] == 33
        assert result.retrieval_diagnostics["selection_basis"] == "generic-tie-lexical-cut"
        assert result.candidate_count == 5


def test_disclaimer_polarity_and_disclaimer_only_are_recorded():
    assert replay("original").selected_lesson_ids == replay("inverted_disclaimer").selected_lesson_ids
    assert replay("original").selected_lesson_ids != replay("without_disclaimer").selected_lesson_ids
    assert replay("disclaimer_only").lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT


def test_two_stage_document_frequency_changes_winners():
    req = request()
    tied = [
        bridge._as_selection_candidate(v) for v in candidates()
        if bridge._match_candidate(req, bridge._as_selection_candidate(v))[0] == 2
    ]
    assert len(tied) == 33
    scores = cks.contextual_tie_scores(req, tied)
    order = sorted(range(len(tied)), key=lambda i: (-scores[i], tied[i].knowledge_id.casefold()))
    five = [tied[i] for i in order[:5]]
    assert tuple(c.knowledge_id for c in five) == ("LL-50", "LL-18", "LL-9", "LL-55", "LL-56")
    assert {five[i].knowledge_id: scores[order[i]] for i in range(5)} == {
        "LL-50": 154, "LL-18": 114, "LL-9": 114, "LL-55": 109, "LL-56": 109,
    }
    next_scores = cks.contextual_tie_scores(req, five)
    assert dict(zip((c.knowledge_id for c in five), next_scores)) == {
        "LL-50": 19, "LL-18": 13, "LL-9": 13, "LL-55": 13, "LL-56": 14,
    }
    final = sorted(range(5), key=lambda i: (-next_scores[i], five[i].knowledge_id.casefold()))
    assert tuple(five[i].knowledge_id for i in final[:3]) == ("LL-50", "LL-56", "LL-18")
    assert tuple(c.knowledge_id for c in five[:3]) == ("LL-50", "LL-18", "LL-9")


def test_legacy_pre4066_lexical_counterfactual(monkeypatch):
    # Monkeypatching scores to zero models the earlier lexical tie mechanism.
    # It is not a live pre-merge read or a second production checkout.
    zero = lambda _req, tied: [0] * len(list(tied))
    monkeypatch.setattr(bridge, "contextual_tie_scores", zero)
    monkeypatch.setattr(cks, "contextual_tie_scores", zero)
    result = replay()
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-10", "LL-18", "LL-21")


def test_row_order_does_not_change_frozen_selection():
    original = rows()
    assert replay(input_rows=original).selected_lesson_ids == replay(input_rows=original[::-1]).selected_lesson_ids
