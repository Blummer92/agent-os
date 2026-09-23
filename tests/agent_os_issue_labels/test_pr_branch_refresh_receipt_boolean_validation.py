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
        trigger=trigger(),
        github_client=github,
        repository_root="/repo",
        invocation_id="actions:strict-bool",
        environment={},
        refresh_callable=refresh,
    )
    return github, result


def test_malformed_authorization_consumed_never_publishes_receipt():
    for value in ("false", 0, None, [], {}):
        github, result = _run("authorization_consumed", value)
        assert result.status == "needs-decision"
        assert result.reason_codes == ("actions.malformed-refresh-receipt",)
        assert result.mutation_count == 0
        assert result.side_effects_performed is False
        assert not github.repo.issue.created


def test_malformed_side_effects_never_become_positive_evidence():
    for value in ("false", 0, None, [], {}):
        github, result = _run("side_effects_performed", value)
        assert result.status == "needs-decision"
        assert result.reason_codes == ("actions.malformed-refresh-receipt",)
        assert result.mutation_count == 0
        assert result.side_effects_performed is False
        assert not github.repo.issue.created
