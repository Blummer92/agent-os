import pytest

from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    IssuePlanCurrentStateComparison,
    IssuePlanCurrentStateOutcome,
)


def _comparison(**overrides):
    values = {
        "expected_evidence_id": "expected",
        "current_evidence_id": "current",
        "expected_fingerprint": "expected-fingerprint",
        "current_fingerprint": "current-fingerprint",
        "changed_bindings": (),
        "outcome": IssuePlanCurrentStateOutcome.CURRENT,
        "reason_codes": (),
        "details": (),
    }
    values.update(overrides)
    return IssuePlanCurrentStateComparison(**values)


@pytest.mark.parametrize("details", [(123,), (None,), ({"not": "text"},)])
def test_issueplan_current_state_rejects_non_string_detail_items(details):
    with pytest.raises((TypeError, ValueError)):
        _comparison(details=details)


def test_issueplan_current_state_rejects_empty_detail_items():
    with pytest.raises(ValueError, match="details must be non-empty strings"):
        _comparison(details=("",))


def test_issueplan_current_state_preserves_valid_detail_items():
    comparison = _comparison(details=("first", "second", "first"))
    assert comparison.details == ("first", "second", "first")
