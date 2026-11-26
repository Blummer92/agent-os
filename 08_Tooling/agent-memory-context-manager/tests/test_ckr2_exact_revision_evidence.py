"""Exact-revision preflight: above generic metadata, below policy proof."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

import pytest

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest, KnowledgeCurrentness,
    _match_candidate, select_coding_knowledge,
)
from agent_memory_context_manager.lesson_activation_bridge import (
    _as_selection_candidate, describe_selection_basis, normalize_lesson_row,
)
from agent_memory_context_manager.lesson_retrieval_orchestrator import orchestrate_lesson_retrieval

ROWS = json.loads((Path(__file__).parent / "fixtures" / "ckr2_exact_revision_evidence.json").read_text())["rows"]
REQUEST = CodingKnowledgeRequest(
    task_reference="Review which code revision the CKR lesson selection actually executed.",
    ecosystem_hints=("agent-os",),
    capability_keywords=("CKR6", "exact-head evidence", "lesson preflight"),
    specialized_knowledge_required=True,
)
REASON = "executed-revision-evidence-text-match"


def row(name, number=None):
    item = ROWS[name]
    number = number or item["number"]
    text = lambda s: {"type": "rich_text", "rich_text": [{"type": "text", "plain_text": s, "text": {"content": s}}]}
    select = lambda s: {"type": "select", "select": {"name": s}}
    return {
        "object": "page", "id": f"offline-row-{number}", "url": f"https://www.notion.so/offline-row-{number}",
        "last_edited_time": "2026-11-26T13:34:35.858Z",
        "properties": {
            "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": number}},
            "Lesson Learned": {"type": "title", "title": [{"type": "text", "plain_text": item["Lesson Learned"]}]},
            "Guardrail": text(item["Guardrail"]),
            "What To Do Next Time": text(item["What To Do Next Time"]),
            "Source Link": {"type": "url", "url": item["Source Link"]},
            "Status": select("New"), "Surface Before Work?": {"type": "checkbox", "checkbox": True},
            "Area": select("Governance"), "Learning Type": select("QA feedback"),
            "Applies To": {"type": "multi_select", "multi_select": []},
        },
    }


class ExactRevisionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.real = normalize_lesson_row(row("LL-98"))
        self.near = normalize_lesson_row(row("D-4102"))
        self.positive = _as_selection_candidate(self.real)
        self.negative = _as_selection_candidate(self.near)

    def test_controlled_positive_and_same_metadata_near_miss(self):
        self.assertEqual(_match_candidate(REQUEST, self.positive), (2, (REASON,)))
        self.assertEqual(_match_candidate(REQUEST, self.negative), (0, ()))
        decision = select_coding_knowledge(REQUEST, (self.negative, self.positive))
        self.assertEqual([s.candidate.knowledge_id for s in decision.selected], ["LL-98"])

    def test_no_lesson_id_hardcoding(self):
        other = replace(self.positive, knowledge_id="LL-5000")
        self.assertEqual(_match_candidate(REQUEST, other), (2, (REASON,)))

    def test_untrusted_source_or_wrong_ecosystem_cannot_qualify(self):
        for c in (replace(self.positive, source_system="untrusted-data"),
                  replace(self.positive, ecosystem="git")):
            self.assertEqual(_match_candidate(REQUEST, c), (0, ()))

    def test_title_and_guidance_must_agree(self):
        for c in (replace(self.positive, name=self.negative.name),
                  replace(self.positive, use_when=self.negative.use_when),
                  replace(self.positive, use_when=("Record the SHA actually executed.",)),
                  replace(self.positive, name="Do not " + self.positive.name.lower())):
            self.assertEqual(_match_candidate(REQUEST, c), (0, ()))

    def test_contradiction_cannot_be_hidden_in_later_guidance(self):
        for kwargs in (
            {"use_when": self.positive.use_when + ("Do not record the SHA actually executed.",)},
            {"avoid_when": self.positive.avoid_when + ("Never compare fixtures against main and the exact PR head.",)},
            {"use_when": (self.positive.use_when[0] + " Do not record the SHA actually executed.",)},
        ):
            self.assertEqual(_match_candidate(REQUEST, replace(self.positive, **kwargs)), (0, ()))

    def test_explicit_mechanism_no_generic_fallback_for_near_miss(self):
        request = replace(REQUEST, capability_keywords=(*REQUEST.capability_keywords, "quality-assurance"))
        self.assertEqual(_match_candidate(request, self.negative), (0, ()))
        unrelated = replace(request, capability_keywords=("quality-assurance",))
        self.assertGreater(_match_candidate(unrelated, self.negative)[0], 0)

    def test_receipt_diagnostics_use_existing_tie_basis(self):
        basis = describe_selection_basis(REQUEST, (self.real, self.near), identity_route=False)
        self.assertEqual((basis.basis, basis.tied_identities), ("generic-unique", 1))
        multiple = tuple(normalize_lesson_row(row("LL-98", n)) for n in range(301, 305))
        tie = describe_selection_basis(REQUEST, multiple, identity_route=False)
        self.assertEqual((tie.basis, tie.tied_identities), ("generic-tie-lexical-cut", 4))

# Collect each case independently so pytest emits one JUnit testcase per result.
@pytest.mark.parametrize("hints", [(), ("exact-head evidence",), ("lesson preflight",), ("CKR6",)])
def test_explicit_pair_is_required(hints):
    positive = _as_selection_candidate(normalize_lesson_row(row("LL-98")))
    request = replace(REQUEST, capability_keywords=hints, known_knowledge_refs=("LL-98",))
    assert _match_candidate(request, positive) == (0, ())


def test_ecosystem_is_required():
    positive = _as_selection_candidate(normalize_lesson_row(row("LL-98")))
    assert _match_candidate(replace(REQUEST, ecosystem_hints=("git",)), positive) == (0, ())


@pytest.mark.parametrize("field", [
    {"currentness": KnowledgeCurrentness.STALE},
    {"canonical_github_refs": (), "evidence_refs": ()},
], ids=["stale", "missing-provenance"])
def test_selection_still_requires_currentness_and_provenance(field):
    positive = _as_selection_candidate(normalize_lesson_row(row("LL-98")))
    result = select_coding_knowledge(REQUEST, (replace(positive, **field),))
    assert result.sufficiency_status.value != "sufficient"


@pytest.mark.parametrize("known", [(), ("LL-98",)], ids=["search", "known-id"])
def test_offline_retrieval_uses_the_rule_with_and_without_known_id(known):
    def read(query):
        alts = query.get("filter", {}).get("or")
        rows = [row("LL-98")] if alts and all("unique_id" in a for a in alts) else [row("D-4102"), row("LL-98")]
        return {"results": rows, "has_more": False, "next_cursor": None}

    result = orchestrate_lesson_retrieval(replace(REQUEST, known_knowledge_refs=known), execute_read=read)
    assert result.selected_lesson_ids == ("LL-98",)
    assert result.lesson_retrieval_status.value == "sufficient"
