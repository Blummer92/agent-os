"""CKR PR-2 production-invariance: existing CKR2 selection outputs must be
byte-identical with (A) no registry, (B) an empty registry, and (C) a
populated synthetic test registry plus a shadow evaluation.

No production file is imported by the shadow evaluator and no production
function takes a registry argument, so the registry cannot influence
selection. These tests prove that property on the exact production
selection entry point instead of asserting it from the code shape alone.
"""

from __future__ import annotations

import json

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeCandidate,
    CodingKnowledgeRequest,
    KnowledgeCurrentness,
    select_coding_knowledge,
)
from agent_memory_context_manager.lesson_applicability import (
    ShadowLessonState,
    TaskEvidence,
    VerifiedObservation,
    describe_applicability_match,
    empty_registry_dict,
    validate_registry,
)
from test_lesson_applicability import (
    BOUNDARIES,
    MECHANISMS,
    REVISION,
    lesson_state,
    record_dict,
    registry_dict,
    task,
    valid_record,
    verified,
)

REPO = "Blummer92/agent-os"


def _candidate(**overrides):
    value = {
        "knowledge_id": "LL-12",
        "source_system": "notion-lessons-learned",
        "source_revision": REVISION,
        "currentness": KnowledgeCurrentness.CURRENT,
        "name": "Prefer explicit closing references",
        "ecosystem": "python",
        "library_name": "pytest",
        "capability_kind": "issue-acceptance",
        "keywords": ("issue-acceptance",),
        "use_when": ("Resolve exactly one explicit closing-keyword target.",),
        "avoid_when": (),
        "canonical_github_refs": (
            "https://github.com/Blummer92/agent-os/issues/100",
        ),
        "evidence_refs": ("https://github.com/Blummer92/agent-os/pull/101",),
    }
    value.update(overrides)
    return CodingKnowledgeCandidate(**value)


def _request(**overrides):
    value = {
        "task_reference": "issue:#4029",
        "ecosystem_hints": ("python",),
        "library_hints": ("pytest",),
        "capability_keywords": ("issue-acceptance",),
        "target_path_hints": ("08_Tooling/agent-memory-context-manager/src/pytest_plugin.py",),
        "canonical_rule_refs": ("https://github.com/Blummer92/agent-os/issues/100",),
    }
    value.update(overrides)
    return CodingKnowledgeRequest(**value)


def _selection_json(request, candidates):
    return select_coding_knowledge(request, candidates).to_json()


def _with_registry_variants(request, candidates):
    """Selection JSON under (A) no registry, (B) empty, (C) populated."""
    baseline = _selection_json(request, candidates)
    empty = validate_registry(empty_registry_dict())
    assert empty.valid
    after_empty = _selection_json(request, candidates)
    populated = validate_registry(
        registry_dict(record_dict()), mechanisms=MECHANISMS, boundaries=BOUNDARIES
    )
    assert populated.valid
    shadow = describe_applicability_match(
        valid_record(),
        lesson_state(),
        task(),
        verified_observations=(verified(),),
    )
    assert shadow.matched is True
    after_populated = _selection_json(request, candidates)
    return baseline, after_empty, after_populated


def test_selection_byte_identical_with_registry():
    """M8 detector: a populated registry plus a shadow match cannot move
    production selection by even one byte."""
    request = _request()
    candidates = (_candidate(),)
    baseline, after_empty, after_populated = _with_registry_variants(request, candidates)
    assert after_empty == baseline
    assert after_populated == baseline
    parsed = json.loads(baseline)
    assert parsed["sufficiency_status"] == "sufficient"
    assert parsed["selected"][0]["knowledge_id"] == "LL-12"
    assert parsed["selected"][0]["reason_codes"] == [
        "exact-library-match",
        "target-path-match",
    ]


def test_selection_byte_identical_with_registry_insufficient_case():
    request = _request(
        capability_keywords=("unrelated-capability",),
        library_hints=(),
        target_path_hints=(),
    )
    candidates = (_candidate(),)
    baseline, after_empty, after_populated = _with_registry_variants(request, candidates)
    assert after_empty == baseline
    assert after_populated == baseline
    assert json.loads(baseline)["sufficiency_status"] == "insufficient"


def test_selection_byte_identical_with_registry_conflict_cases():
    cases = [
        # Duplicate identity conflict.
        (_request(), (_candidate(), _candidate(name="Different name"),)),
        # Stale relevant candidate.
        (_request(), (_candidate(currentness=KnowledgeCurrentness.STALE),)),
        # Unverifiable relevant candidate.
        (_request(), (_candidate(currentness=KnowledgeCurrentness.UNVERIFIABLE),)),
        # Authority conflict.
        (_request(), (_candidate(authority_conflict=True),)),
        # Candidate budget exceeded (6 distinct candidates).
        (
            _request(),
            tuple(_candidate(knowledge_id=f"LL-{20 + i}") for i in range(6)),
        ),
        # Knowledge not needed.
        (
            _request(specialized_knowledge_required=False),
            (_candidate(),),
        ),
        # CKR6 mutation-boundary special match.
        (
            _request(
                capability_keywords=("ckr6 mutation boundary",),
                library_hints=(),
                ecosystem_hints=(),
            ),
            (
                _candidate(
                    library_name=None,
                    name="CKR6 mutation boundary guard",
                    use_when=("CKR6 mutation boundary handling.",),
                    keywords=(),
                ),
            ),
        ),
    ]
    for request, candidates in cases:
        baseline, after_empty, after_populated = _with_registry_variants(
            request, candidates
        )
        assert after_empty == baseline
        assert after_populated == baseline


def test_selection_byte_identical_with_registry_keyword_overlap():
    request = _request(library_hints=(), target_path_hints=())
    candidates = (_candidate(),)
    baseline, after_empty, after_populated = _with_registry_variants(request, candidates)
    assert after_empty == baseline
    assert after_populated == baseline
    parsed = json.loads(baseline)
    assert parsed["sufficiency_status"] == "sufficient"
    assert parsed["selected"][0]["reason_codes"] == ["ecosystem-capability-match"]


def test_registry_contents_cannot_affect_production_selection():
    """Metamorphic (6): two different populated registries, one selection."""
    request = _request()
    candidates = (_candidate(),)
    baseline = _selection_json(request, candidates)
    first = validate_registry(
        registry_dict(record_dict()), mechanisms=MECHANISMS, boundaries=BOUNDARIES
    )
    second = validate_registry(
        registry_dict(
            record_dict(
                lesson_id="LL-13",
                mechanisms=["test-mechanism-beta"],
                positive_conditions=[
                    {"mechanism": "test-mechanism-beta", "boundary_id": None}
                ],
            )
        ),
        mechanisms=MECHANISMS,
        boundaries=BOUNDARIES,
    )
    assert first.valid and second.valid
    for registry in (first, second):
        for record in registry.records:
            describe_applicability_match(
                record,
                ShadowLessonState(
                    lesson_id=record.lesson_id,
                    source_revision=record.source_revision,
                    title="Prefer explicit closing references",
                    archived=False,
                    surface_before_work=True,
                    currentness="current",
                ),
                TaskEvidence(task_reference="https://github.com/Blummer92/agent-os/issues/4029"),
                verified_observations=(
                    VerifiedObservation(
                        mechanism="test-mechanism-beta",
                        boundary_id=None,
                        observation_id="obs-9",
                        repository=REPO,
                        freshness="fresh",
                    ),
                ),
            )
        assert _selection_json(request, candidates) == baseline
