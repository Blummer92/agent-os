"""#3402 mergeability evidence classifier tests (Slice 6, Phase 1).

Behavioral tests for the pure-local classifier in
``scripts/agent_os_issue_acceptance/merge_candidate_evidence.py``: every
fixture case in ``fixtures/merge_candidate_evidence_cases.yml`` is executed
through ``classify_merge_candidate_evidence`` and asserted on disposition +
reason codes. Sequential fixture steps model one candidate re-reading fresh
evidence between classifications.

Issue #3402 stays OPEN; fixture evidence is partial implementation evidence.
"""

import dataclasses
from itertools import product
from pathlib import Path

import pytest
import yaml

from scripts.agent_os_issue_acceptance.merge_candidate_evidence import (
    DISPOSITIONS,
    REASON_CODES,
    MergeCandidateClassification,
    MergeCandidateDisposition,
    MergeCandidateEvidence,
    classify_merge_candidate_evidence,
)

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = yaml.safe_load(
    (FIXTURES / "merge_candidate_evidence_cases.yml").read_text()
)["cases"]
CASES_BY_ID = {case["id"]: case for case in CORPUS}

EVIDENCE_FIELDS = (
    "pr_open",
    "is_draft",
    "mergeable",
    "aggregate",
    "head_sha",
    "head_sha_stable",
    "checks_failing",
    "reacquires_remaining",
    "polls_remaining",
)

EXPECTED_CASE_IDS = {
    "3402-transient-mergeability",
    "3402-persistent-mergeability-false",
    "item-local-checks-failing",
    "all-green-exact-head",
    "draft-pr",
    "closed-pr",
    "mergeability-unknown-then-ceiling",
}


def _green(**overrides):
    fields = {
        "pr_open": True,
        "is_draft": False,
        "mergeable": True,
        "aggregate": "success",
        "head_sha": "f3a927aeeeb4756c2d90ad89f23b919522b20078",
        "head_sha_stable": True,
        "checks_failing": False,
        "reacquires_remaining": 2,
        "polls_remaining": 5,
    }
    fields.update(overrides)
    return MergeCandidateEvidence(**fields)


# ---------------------------------------------------------------------------
# Fixture corpus schema
# ---------------------------------------------------------------------------


def test_fixture_case_ids_cover_expected():
    assert EXPECTED_CASE_IDS <= set(CASES_BY_ID)
    assert len(set(CASES_BY_ID)) == len(CORPUS)


def test_fixture_steps_carry_complete_evidence_and_closed_expectations():
    for case in CORPUS:
        assert case["id"] and case["steps"], case["id"]
        for step in case["steps"]:
            assert set(step["evidence"]) == set(EVIDENCE_FIELDS), (case["id"], step)
            assert step["expected_disposition"] in DISPOSITIONS, (case["id"], step)
            assert step["expected_reason_codes"], (case["id"], step)
            assert set(step["expected_reason_codes"]) <= REASON_CODES, (case["id"], step)


# ---------------------------------------------------------------------------
# Fixture cases: execute the classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", sorted(EXPECTED_CASE_IDS))
def test_fixture_case(case_id):
    case = CASES_BY_ID[case_id]
    for index, step in enumerate(case["steps"]):
        evidence = MergeCandidateEvidence(**step["evidence"])
        classification = classify_merge_candidate_evidence(evidence)

        assert classification.disposition == MergeCandidateDisposition(
            step["expected_disposition"]
        ), (case_id, index)
        assert classification.reason_codes == tuple(step["expected_reason_codes"]), (
            case_id,
            index,
        )
        # The classification binds the exact head SHA the evidence was read on.
        assert classification.head_sha == step["evidence"]["head_sha"], (case_id, index)


# ---------------------------------------------------------------------------
# Sequential-behavior spot checks
# ---------------------------------------------------------------------------


def test_transient_mergeability_false_is_not_terminal():
    # #3402: a single mergeable=false with budget left must not block.
    first = classify_merge_candidate_evidence(_green(mergeable=False))
    assert first.disposition == MergeCandidateDisposition.REREAD_MERGEABILITY
    assert first.reason_codes == ("mergeability-false-transient",)

    second = classify_merge_candidate_evidence(
        _green(mergeable=True, reacquires_remaining=1)
    )
    assert second.disposition == MergeCandidateDisposition.PROCEED
    assert second.reason_codes == ("all-evidence-green",)


def test_persistent_mergeability_false_blocks_only_this_item():
    # #3402: false on every re-read blocks THIS item, not the batch.
    final = classify_merge_candidate_evidence(
        _green(mergeable=False, reacquires_remaining=0)
    )
    assert final.disposition == MergeCandidateDisposition.BLOCKED_ITEM_LOCAL
    assert final.reason_codes == ("mergeability-false-persistent",)




# ---------------------------------------------------------------------------
# Precedence: guard rails beat waits and re-reads
# ---------------------------------------------------------------------------



def test_stale_head_beats_all_green():
    classification = classify_merge_candidate_evidence(_green(head_sha_stable=False))
    assert classification.disposition == MergeCandidateDisposition.BLOCKED_ITEM_LOCAL
    assert classification.reason_codes == ("head-sha-changed",)



def test_failed_aggregate_beats_mergeability_reread():
    classification = classify_merge_candidate_evidence(
        _green(aggregate="failed", mergeable=None, reacquires_remaining=2)
    )
    assert classification.disposition == MergeCandidateDisposition.BLOCKED_ITEM_LOCAL
    assert classification.reason_codes == ("aggregate-failed",)


def test_unknown_aggregate_is_blocked_item_local():
    classification = classify_merge_candidate_evidence(_green(aggregate="unknown"))
    assert classification.disposition == MergeCandidateDisposition.BLOCKED_ITEM_LOCAL
    assert classification.reason_codes == ("aggregate-state-unknown",)



# ---------------------------------------------------------------------------
# Closed vocabularies hold over the full evidence cross-product
# ---------------------------------------------------------------------------


def test_closed_vocabularies_over_evidence_matrix():
    for aggregate, mergeable, reacquires, polls in product(
        ("success", "in_progress", "failed", "unknown"),
        (True, False, None),
        (0, 1),
        (0, 1),
    ):
        for pr_open, is_draft, head_sha_stable, checks_failing in product(
            (True, False), repeat=4
        ):
            classification = classify_merge_candidate_evidence(
                _green(
                    pr_open=pr_open,
                    is_draft=is_draft,
                    mergeable=mergeable,
                    aggregate=aggregate,
                    head_sha_stable=head_sha_stable,
                    checks_failing=checks_failing,
                    reacquires_remaining=reacquires,
                    polls_remaining=polls,
                )
            )
            assert classification.disposition.value in DISPOSITIONS
            assert set(classification.reason_codes) <= REASON_CODES
            assert classification.reason_codes  # exactly one primary reason


# ---------------------------------------------------------------------------
# Classifier contract: pure, deterministic, strict inputs
# ---------------------------------------------------------------------------


def test_classification_is_deterministic_and_pure():
    evidence = _green(mergeable=False)
    first = classify_merge_candidate_evidence(evidence)
    second = classify_merge_candidate_evidence(_green(mergeable=False))
    assert first == second
    assert isinstance(first.disposition, str)
    assert first.disposition == "reread_mergeability"
    assert first.disposition.value == "reread_mergeability"


def test_evidence_and_classification_are_frozen():
    evidence = _green()
    classification = classify_merge_candidate_evidence(evidence)
    with pytest.raises(dataclasses.FrozenInstanceError):
        evidence.pr_open = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        classification.disposition = MergeCandidateDisposition.PROCEED  # type: ignore[misc]


def test_classify_rejects_non_evidence():
    with pytest.raises(TypeError):
        classify_merge_candidate_evidence("not evidence")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        classify_merge_candidate_evidence(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides, error",
    [
        ({"pr_open": "yes"}, TypeError),
        ({"pr_open": 1}, TypeError),
        ({"is_draft": 0}, TypeError),
        ({"mergeable": 1}, TypeError),
        ({"mergeable": "false"}, TypeError),
        ({"aggregate": "completed"}, ValueError),
        ({"aggregate": None}, ValueError),
        ({"aggregate": "SUCCESS"}, ValueError),
        ({"head_sha": ""}, ValueError),
        ({"head_sha": "   "}, ValueError),
        ({"head_sha": None}, ValueError),
        ({"head_sha_stable": "true"}, TypeError),
        ({"checks_failing": None}, TypeError),
        ({"reacquires_remaining": -1}, ValueError),
        ({"reacquires_remaining": True}, TypeError),
        ({"reacquires_remaining": 1.5}, TypeError),
        ({"polls_remaining": -2}, ValueError),
        ({"polls_remaining": False}, TypeError),
        ({"polls_remaining": "3"}, TypeError),
    ],
)
def test_invalid_evidence_raises(overrides, error):
    with pytest.raises(error):
        _green(**overrides)


def test_classification_rejects_open_vocabulary_reason_codes():
    with pytest.raises(ValueError):
        MergeCandidateClassification(
            disposition=MergeCandidateDisposition.PROCEED,
            reason_codes=("something-made-up",),
            head_sha="f3a927aeeeb4756c2d90ad89f23b919522b20078",
        )
