"""#3308: pure pre-create reconciliation classifier.

Issue numbers below are #3308's preserved regression seeds used as fixture
shapes; the classifier never hard-codes them, and their live state is the
caller's evidence, not an assumption made here.
"""

import ast
from pathlib import Path

import pytest

from navigation_registry import reconciliation as rec
from navigation_registry.reconciliation import (
    CapabilityMatch,
    LineageCandidate,
    ReconciliationInput,
    classify_proposed_work,
)

MODULE = Path(rec.__file__)


def evidence(**overrides):
    values = {"subject": "proposed work", "github_search_complete": True}
    values.update(overrides)
    return ReconciliationInput(**values)


def classify(**overrides):
    return classify_proposed_work(evidence(**overrides))


def open_issue(number, *, match="exact", stage=None):
    return LineageCandidate(issue_number=number, state="open", match=match, lifecycle_stage=stage)


def closed_issue(number, *, reason="completed", match="exact", successor=None, successor_state=None,
                 successor_stage=None):
    return LineageCandidate(
        issue_number=number, state="closed", match=match, state_reason=reason,
        successor_issue_number=successor, successor_state=successor_state,
        successor_lifecycle_stage=successor_stage,
    )


# --- seed families -------------------------------------------------------------

def test_worksheet_request_with_current_open_owner_reuses_it():
    result = classify(lineage=(open_issue(3259), closed_issue(3152)))
    assert result.disposition == rec.REUSE_CURRENT_OWNER
    assert result.owner_issue_number == 3259
    assert result.evidence_issue_numbers == (3152, 3259)


def test_slides_placement_owner_with_active_pr_continues_current_work():
    result = classify(lineage=(open_issue(3257, stage="draft-pr"),))
    assert result.disposition == rec.CONTINUE_CURRENT_WORK
    assert result.owner_issue_number == 3257
    assert "lifecycle.draft-pr" in result.reason_codes


def test_lp_request_with_only_completed_history_is_regression_evidence_not_actionable():
    result = classify(lineage=(closed_issue(646), closed_issue(2914)))
    assert result.disposition == rec.HISTORICAL_REGRESSION_EVIDENCE
    assert result.owner_issue_number is None


def test_closed_issue_with_current_successor_returns_the_successor():
    result = classify(lineage=(closed_issue(3152, successor=3259, successor_state="open"),))
    assert result.disposition == rec.REUSE_CURRENT_OWNER
    assert result.owner_issue_number == 3259
    assert "github.current-successor-owner" in result.reason_codes


def test_successor_with_active_pr_continues_work():
    result = classify(lineage=(closed_issue(2826, successor=3139, successor_state="open",
                                            successor_stage="review"),))
    assert (result.disposition, result.owner_issue_number) == (rec.CONTINUE_CURRENT_WORK, 3139)


def test_codespaces_request_extends_the_registered_capability():
    result = classify(capabilities=(CapabilityMatch("codespaces-governed-runner", "active"),))
    assert result.disposition == rec.EXTEND_EXISTING_CAPABILITY
    assert result.capability_id == "codespaces-governed-runner"


def test_not_planned_or_duplicate_history_is_superseded():
    result = classify(lineage=(closed_issue(97, reason="not_planned"), closed_issue(3309, reason="duplicate")))
    assert result.disposition == rec.SUPERSEDED_OR_RETIRED


def test_replaced_capability_is_superseded():
    result = classify(capabilities=(CapabilityMatch("old-runner", "replaced"),))
    assert (result.disposition, result.capability_id) == (rec.SUPERSEDED_OR_RETIRED, "old-runner")


# --- precedence: GitHub is authoritative ---------------------------------------

def test_open_owner_wins_over_navigation_no_match_and_capability():
    result = classify(
        lineage=(open_issue(3259),),
        capabilities=(CapabilityMatch("worksheet-engine", "active"),),
        navigation_applicable=True,
        navigation_outcome="no-cached-match",
    )
    assert result.disposition == rec.REUSE_CURRENT_OWNER


def test_open_owner_is_reused_even_when_navigation_is_stale():
    result = classify(lineage=(open_issue(3259),), navigation_applicable=True,
                      navigation_outcome="stale-or-unverified")
    assert result.disposition == rec.REUSE_CURRENT_OWNER
    assert result.reason_codes[0] == "navigation.stale-or-unverified"


def test_merged_pr_on_open_owner_still_routes_to_the_owner_not_new_work():
    result = classify(lineage=(open_issue(3306, stage="merged"),))
    assert result.disposition == rec.REUSE_CURRENT_OWNER
    assert "lifecycle.merged" in result.reason_codes


# --- fail closed ----------------------------------------------------------------

def test_incomplete_github_search_is_manual_review_not_new_work():
    result = classify(github_search_complete=False)
    assert result.disposition == rec.MANUAL_REVIEW
    assert result.reason_codes == ("github.lineage-incomplete",)


@pytest.mark.parametrize(
    "lineage",
    [
        (open_issue(1), open_issue(2)),
        (closed_issue(1, successor=3, successor_state="open"), closed_issue(2, successor=4, successor_state="open")),
        (closed_issue(1, successor=3, successor_state="closed"),),
        (open_issue(5, match="related"),),
    ],
)
def test_ambiguous_lineage_is_manual_review(lineage):
    assert classify(lineage=lineage).disposition == rec.MANUAL_REVIEW


def test_multiple_live_capabilities_are_manual_review():
    result = classify(capabilities=(CapabilityMatch("a", "active"), CapabilityMatch("b", "experimental")))
    assert result.disposition == rec.MANUAL_REVIEW


@pytest.mark.parametrize(
    "outcome",
    [None, "stale-or-unverified", "existing-match", "duplicate-risk-review", "manual-review"],
)
def test_navigation_evidence_other_than_a_fresh_no_match_blocks_new_work(outcome):
    result = classify(navigation_applicable=True, navigation_outcome=outcome)
    assert result.disposition == rec.MANUAL_REVIEW
    assert result.reason_codes == (f"navigation.{outcome or 'evidence-missing'}",)


def test_no_match_anywhere_is_only_a_candidate_with_no_creation_authority():
    for overrides in ({}, {"navigation_applicable": True, "navigation_outcome": "no-cached-match"}):
        result = classify(**overrides)
        assert result.disposition == rec.CANDIDATE_NEW_WORK
        assert "new-work.requires-creation-admission" in result.reason_codes
        assert result.authorizes_issue_creation is False


def test_related_closed_history_alone_does_not_block_a_candidate():
    result = classify(lineage=(closed_issue(1563, match="related"),))
    assert result.disposition == rec.CANDIDATE_NEW_WORK
    assert result.evidence_issue_numbers == (1563,)


# --- result contract --------------------------------------------------------------

def test_every_result_projects_no_authority_and_requires_live_verification():
    for overrides in (
        {}, {"github_search_complete": False}, {"lineage": (open_issue(1),)},
        {"capabilities": (CapabilityMatch("x", "active"),)},
    ):
        result = classify(**overrides)
        assert result.disposition in rec.DISPOSITIONS
        payload = result.to_dict()
        assert payload["authorizes_issue_creation"] is False
        assert payload["authorizes_mutation"] is False
        assert payload["execution_authorized"] is False
        assert payload["live_verification_required"] is True


def test_identical_evidence_gives_identical_results_and_digest():
    first = classify(lineage=(open_issue(7),))
    second = classify(lineage=(open_issue(7),))
    assert first == second
    assert first.input_digest.startswith("reconciliation-input:")
    assert first.input_digest != classify(lineage=(open_issue(8),)).input_digest


def test_issue_and_capability_identities_stay_distinct():
    result = classify(lineage=(closed_issue(3024),), capabilities=(CapabilityMatch("3024", "active"),))
    assert result.disposition == rec.EXTEND_EXISTING_CAPABILITY
    assert result.capability_id == "3024" and result.owner_issue_number is None
    assert result.evidence_issue_numbers == (3024,)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"issue_number": 0, "state": "open", "match": "exact"},
        {"issue_number": True, "state": "open", "match": "exact"},
        {"issue_number": 1, "state": "merged", "match": "exact"},
        {"issue_number": 1, "state": "open", "match": "fuzzy"},
        {"issue_number": 1, "state": "open", "match": "exact", "state_reason": "completed"},
        {"issue_number": 1, "state": "closed", "match": "exact"},
        {"issue_number": 1, "state": "closed", "match": "exact", "state_reason": "completed", "lifecycle_stage": "review"},
        {"issue_number": 1, "state": "closed", "match": "exact", "state_reason": "completed", "successor_issue_number": 1, "successor_state": "open"},
        {"issue_number": 1, "state": "closed", "match": "exact", "state_reason": "completed", "successor_state": "open"},
        {"issue_number": 1, "state": "open", "match": "exact", "lifecycle_stage": "shipped"},
        {"issue_number": 1, "state": "open", "match": "exact", "lifecycle_stage": "closed"},
        {"issue_number": 1, "state": "closed", "match": "exact", "state_reason": "completed", "successor_issue_number": 2, "successor_state": "closed", "successor_lifecycle_stage": "review"},
    ],
)
def test_malformed_lineage_is_rejected(kwargs):
    with pytest.raises(ValueError):
        LineageCandidate(**kwargs)


def test_malformed_input_is_rejected():
    with pytest.raises(ValueError):
        evidence(lineage=(open_issue(1), open_issue(1)))
    with pytest.raises(ValueError):
        evidence(navigation_outcome="no-cached-match")
    with pytest.raises(ValueError):
        evidence(navigation_applicable=True, navigation_outcome="safe-to-create")
    with pytest.raises(TypeError):
        evidence(github_search_complete="yes")
    with pytest.raises(TypeError):
        evidence(lineage=[open_issue(1)])
    with pytest.raises(ValueError):
        CapabilityMatch("x", "retired")
    with pytest.raises(TypeError):
        classify_proposed_work({"subject": "x"})


def test_module_is_pure_no_io_or_external_imports():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "hashlib", "json", "dataclasses", "typing"}
    source = MODULE.read_text(encoding="utf-8")
    for forbidden in ("open(", "requests", "urllib", "subprocess", "socket"):
        assert forbidden not in source


# --- independent QA findings (contradictory or ambiguous successor evidence) ---

def test_conflicting_facts_for_one_successor_are_manual_review_not_seed_dependent():
    lineage = (
        closed_issue(1, successor=9, successor_state="open", successor_stage="draft-pr"),
        closed_issue(2, successor=9, successor_state="open", successor_stage="planning"),
    )
    result = classify(lineage=lineage)
    assert result.disposition == rec.MANUAL_REVIEW
    assert "github.successor-facts-conflict" in result.reason_codes


def test_successor_contradicting_its_own_lineage_entry_is_manual_review():
    result = classify(lineage=(closed_issue(1, successor=2, successor_state="open"), closed_issue(2)))
    assert result.disposition == rec.MANUAL_REVIEW
    assert result.owner_issue_number is None


def test_successor_reported_open_and_closed_is_manual_review():
    lineage = (
        closed_issue(1, successor=9, successor_state="open"),
        closed_issue(2, successor=9, successor_state="closed"),
    )
    assert classify(lineage=lineage).disposition == rec.MANUAL_REVIEW


def test_any_closed_successor_chain_is_manual_review_even_beside_an_open_one():
    lineage = (
        closed_issue(1, successor=8, successor_state="open"),
        closed_issue(2, successor=9, successor_state="closed"),
    )
    assert classify(lineage=lineage).disposition == rec.MANUAL_REVIEW


def test_open_owner_and_a_different_open_successor_are_manual_review():
    lineage = (open_issue(5), closed_issue(1, successor=6, successor_state="open"))
    result = classify(lineage=lineage)
    assert result.disposition == rec.MANUAL_REVIEW
    assert "github.multiple-open-owners" in result.reason_codes


def test_successor_that_is_the_open_owner_is_one_owner():
    lineage = (open_issue(6, stage="review"), closed_issue(1, successor=6, successor_state="open",
                                                          successor_stage="review"))
    result = classify(lineage=lineage)
    assert (result.disposition, result.owner_issue_number) == (rec.CONTINUE_CURRENT_WORK, 6)


def test_related_history_with_a_successor_is_manual_review():
    lineage = (closed_issue(1, match="related", successor=2, successor_state="open"),)
    assert classify(lineage=lineage).disposition == rec.MANUAL_REVIEW


def test_related_closed_history_is_named_in_a_candidate():
    result = classify(lineage=(closed_issue(1563, match="related"),))
    assert result.disposition == rec.CANDIDATE_NEW_WORK
    assert "github.related-history" in result.reason_codes


def test_capability_outranks_completed_history_of_the_same_objective():
    result = classify(lineage=(closed_issue(2087),), capabilities=(CapabilityMatch("visual-placement", "active"),))
    assert result.disposition == rec.EXTEND_EXISTING_CAPABILITY
    assert result.reason_codes == ("github.completed-history", "capability.registered")


def test_results_are_identical_across_input_orderings():
    lineage = (
        closed_issue(1, successor=9, successor_state="open", successor_stage="review"),
        closed_issue(2, successor=9, successor_state="open", successor_stage="review"),
        closed_issue(3, match="related"),
    )
    forward = classify(lineage=lineage)
    backward = classify(lineage=tuple(reversed(lineage)))
    assert (forward.disposition, forward.owner_issue_number, forward.reason_codes) == (
        backward.disposition, backward.owner_issue_number, backward.reason_codes)
    assert forward.disposition == rec.CONTINUE_CURRENT_WORK
