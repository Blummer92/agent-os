"""NEW-N1: partial GraphQL errors do not establish resolved review threads."""
import pytest

from scripts.agent_os_issue_acceptance.merge_applicability import (
    evaluate_merge_dispatch_applicability,
)
from tests.agent_os_issue_acceptance.test_merge_applicability import (
    NOW, REPO, _Client, _PR, _Repo, _Requester, _authorized_record,
    _comments_for, _transport,
)


class ErrorOnPageRequester(_Requester):
    def __init__(self, error_cursor):
        super().__init__([
            [{"isResolved": True}], [{"isResolved": True}],
        ])
        self.error_cursor = error_cursor

    def graphql_query(self, query, variables):
        metadata, payload = super().graphql_query(query, variables)
        if variables["cursor"] == self.error_cursor:
            payload["errors"] = [{"message": "partial thread read failure"}]
        return metadata, payload


@pytest.mark.parametrize("cursor", [None, "1"])
def test_new_n1_partial_graphql_error_never_passes_dispatch_reviews(cursor):
    record = _authorized_record(None)
    requester = ErrorOnPageRequester(cursor)
    client = _Client(
        _Repo(_PR(), _comments_for(None, record)),
        requester=requester,
    )
    receipt = evaluate_merge_dispatch_applicability(
        _transport(), repository=REPO, github_client=client, evaluated_at=NOW,
    )
    assert len(requester.calls) == (1 if cursor is None else 2)
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["merge_authorized"] is False
    assert receipt["reason_codes"] == ["review.threads-unverifiable"]
