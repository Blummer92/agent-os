"""Independent scope controls for the source-owned REST lexical matcher."""
import pytest

from agent_memory_context_manager.coding_knowledge_selection import (
    SufficiencyStatus,
    select_coding_knowledge,
)
from test_ckr2_4026_github_rest_evidence import candidate, request


AFFIRMATIVE = "Reject duplicate GitHub comment IDs across paginated pages."
CONTRADICTORY = "Do not reject duplicate GitHub comment IDs across paginated pages."


def assert_without_relevance(request_value, candidate_value):
    result = select_coding_knowledge(request_value, (candidate_value,))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.reason_codes == ("no-relevant-candidate",)
    assert result.selected == ()
    assert not result.authority_created


@pytest.mark.parametrize("negative_field", ("use_when", "avoid_when"))
def test_explicit_source_contradiction_vetoes_otherwise_affirmative_match(negative_field):
    # Both source-owned fields can contain a contradiction. Merely finding
    # the affirmative clause does not resolve the incompatible guidance.
    changes = {"use_when": (AFFIRMATIVE,)}
    changes[negative_field] = (*changes.get(negative_field, ()), CONTRADICTORY)
    assert_without_relevance(request(), candidate(**changes))


def test_separate_source_fields_cannot_supply_one_action_scope():
    # The source fields carry distinct claims, not parts of one attestation.
    # Joining them before parsing would invent a pagination scope.
    source = candidate(
        use_when=("Reject duplicate GitHub comment IDs", "across paginated pages."),
    )
    assert_without_relevance(request(), source)


def test_caller_prose_cannot_complete_missing_source_action():
    source = candidate(use_when=("Read the GitHub issue comment listing.",))
    assert_without_relevance(request(task_reference=AFFIRMATIVE), source)
