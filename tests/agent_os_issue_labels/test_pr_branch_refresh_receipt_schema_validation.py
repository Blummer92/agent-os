import pytest

from tests.agent_os_issue_labels.test_pr_branch_refresh_actions_runner import (
    FakeComment,
    FakeGithub,
    authorization,
    trigger,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_actions_runner import run_branch_refresh_actions
from scripts.agent_os_issue_labels.pr_branch_refresh_authorization_source import serialize_refresh_authorization_comment


def _run(field, value):
    auth = authorization()
    github = FakeGithub([FakeComment(10, serialize_refresh_authorization_comment(auth))])

    def refresh(**kwargs):
        payload = {
            "status": "blocked",
            "authorization_consumed": False,
            "mutation_count": 0,
            "reason_codes": ("fixture",),
            "side_effects_performed": False,
        }
        payload[field] = value
        return payload

    result = run_branch_refresh_actions(
        trigger=trigger(), github_client=github, repository_root="/repo",
        invocation_id="actions:strict-schema", environment={}, refresh_callable=refresh,
    )
    return github, result


@pytest.mark.parametrize("value", [True, "1", -1, 2, None, [], {}])
def test_malformed_mutation_count_fails_closed(value):
    github, result = _run("mutation_count", value)
    assert result.status == "needs-decision"
    assert result.reason_codes == ("actions.malformed-refresh-receipt",)
    assert result.mutation_count == 0
    assert result.side_effects_performed is False
    assert not github.repo.issue.created


@pytest.mark.parametrize("value", [None, 1, True, "", [], {}])
def test_malformed_status_fails_closed(value):
    github, result = _run("status", value)
    assert result.status == "needs-decision"
    assert result.reason_codes == ("actions.malformed-refresh-receipt",)
    assert not github.repo.issue.created


@pytest.mark.parametrize("value", ["blocked", None, {}, ["ok", 1], [""], [True]])
def test_malformed_reason_codes_fail_closed(value):
    github, result = _run("reason_codes", value)
    assert result.status == "needs-decision"
    assert result.reason_codes == ("actions.malformed-refresh-receipt",)
    assert not github.repo.issue.created
