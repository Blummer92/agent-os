from __future__ import annotations

import inspect

import pytest

from scripts.agent_os_issue_labels.pr_branch_refresh_authorization import (
    BranchRefreshAuthorizationEvidence,
    RefreshAuthorization,
    RefreshAuthorizationState,
    resolve_branch_refresh_authorization,
)

REPO = "Blummer92/agent-os"
HEAD = "a" * 40
MAIN = "b" * 40


def auth(**overrides):
    values = dict(
        schema_version="1.0",
        repository=REPO,
        pr_number=1363,
        base_branch="main",
        expected_head_sha=HEAD,
        expected_main_sha=MAIN,
        allowed_changed_paths=("x.py", "docs/x.md"),
        forbidden_paths=(".github/workflows/x.yml",),
        required_validation_command_ids=("pytest:pr-branch-refresh",),
        branch_refresh_authorized=True,
        label_write_authorized=True,
        owner_decision_reference="github-comment:123",
        state=RefreshAuthorizationState.AUTHORIZED,
    )
    values.update(overrides)
    return RefreshAuthorization(**values)


def resolve(record=None, **overrides):
    values = dict(repository=REPO, pr_number=1363, current_head_sha=HEAD, current_main_sha=MAIN, current_changed_paths=("x.py",))
    values.update(overrides)
    records = [] if record is None else [record]
    return resolve_branch_refresh_authorization(records, **values)


def test_identical_inputs_have_identical_content_identity():
    assert auth().authorization_id == auth().authorization_id


@pytest.mark.parametrize("field,value", [
    ("repository", "other/repo"),
    ("pr_number", 1364),
    ("expected_head_sha", "c" * 40),
    ("expected_main_sha", "d" * 40),
    ("allowed_changed_paths", ("y.py",)),
    ("branch_refresh_authorized", False),
    ("label_write_authorized", False),
])
def test_authority_bearing_change_changes_identity(field, value):
    assert auth().authorization_id != auth(**{field: value}).authorization_id


def test_exact_current_authorization_resolves():
    result = resolve(auth())
    assert result.applicable is True
    assert result.authorization_current is True
    assert result.branch_refresh_authorized is True
    assert result.label_write_authorized is True
    assert result.authorization_id == auth().authorization_id


def test_missing_authorization_fails_closed():
    result = resolve()
    assert result.reason_codes == ("authorization.absent",)
    assert result.branch_refresh_authorized is False


def test_multiple_matching_records_are_ambiguous():
    result = resolve_branch_refresh_authorization(
        [auth(), auth(owner_decision_reference="github-comment:456")],
        repository=REPO, pr_number=1363, current_head_sha=HEAD, current_main_sha=MAIN,
        current_changed_paths=("x.py",),
    )
    assert result.reason_codes == ("authorization.ambiguous",)


def test_stale_main_record_does_not_compete_with_exact_current_record():
    stale = auth(expected_main_sha="c" * 40, owner_decision_reference="old-main")
    current = auth(owner_decision_reference="current-main")
    result = resolve_branch_refresh_authorization(
        [stale, current], repository=REPO, pr_number=1363,
        current_head_sha=HEAD, current_main_sha=MAIN, current_changed_paths=("x.py",),
    )
    assert result.applicable is True
    assert result.authorization_id == current.authorization_id


def test_stale_head_record_does_not_compete_with_exact_current_record():
    stale = auth(expected_head_sha="c" * 40, owner_decision_reference="old-head")
    current = auth(owner_decision_reference="current-head")
    result = resolve_branch_refresh_authorization(
        [stale, current], repository=REPO, pr_number=1363,
        current_head_sha=HEAD, current_main_sha=MAIN, current_changed_paths=("x.py",),
    )
    assert result.applicable is True
    assert result.authorization_id == current.authorization_id


def test_stale_scope_record_does_not_compete_with_exact_current_record():
    stale = auth(allowed_changed_paths=("docs/x.md",), owner_decision_reference="old-scope")
    current = auth(owner_decision_reference="current-scope")
    result = resolve_branch_refresh_authorization(
        [stale, current], repository=REPO, pr_number=1363,
        current_head_sha=HEAD, current_main_sha=MAIN, current_changed_paths=("x.py",),
    )
    assert result.applicable is True
    assert result.authorization_id == current.authorization_id


@pytest.mark.parametrize("state,reason", [
    (RefreshAuthorizationState.CONSUMED, "authorization.consumed"),
    (RefreshAuthorizationState.EXPIRED, "authorization.not-current"),
    (RefreshAuthorizationState.INVALIDATED, "authorization.not-current"),
    (RefreshAuthorizationState.SUPERSEDED, "authorization.not-current"),
])
def test_noncurrent_authorization_fails_closed(state, reason):
    result = resolve(auth(state=state))
    assert reason in result.reason_codes
    assert result.authorization_id is None


def test_authorization_for_another_pr_is_absent_for_target():
    result = resolve(auth(pr_number=999))
    assert result.reason_codes == ("authorization.absent",)


def test_moved_head_is_stale_and_unconsumed():
    result = resolve(auth(), current_head_sha="c" * 40)
    assert result.reason_codes == ("head.moved",)
    assert result.side_effects_performed is False


def test_moved_main_is_stale_and_unconsumed():
    result = resolve(auth(), current_main_sha="c" * 40)
    assert result.reason_codes == ("main.moved",)
    assert result.side_effects_performed is False


def test_scope_expansion_fails_closed():
    result = resolve(auth(), current_changed_paths=("x.py", "new.py"))
    assert result.reason_codes == ("scope.expanded",)


def test_forbidden_path_fails_closed():
    result = resolve(auth(allowed_changed_paths=("x.py", ".github/workflows/x.yml")), current_changed_paths=(".github/workflows/x.yml",))
    assert result.reason_codes == ("scope.forbidden-path",)


def test_label_write_authority_is_not_manufactured():
    result = resolve(auth(label_write_authorized=False))
    assert result.applicable is True
    assert result.label_write_authorized is False


def test_trigger_actor_and_token_are_not_resolver_inputs():
    parameters = set(inspect.signature(resolve_branch_refresh_authorization).parameters)
    assert parameters.isdisjoint({"comment", "actor", "token", "github_token", "environment"})


def test_resolver_performs_no_mutation_and_result_is_bounded():
    result = resolve(auth())
    assert isinstance(result, BranchRefreshAuthorizationEvidence)
    assert result.side_effects_performed is False
    assert len(result.reason_codes) <= 32


def test_resolved_evidence_projects_merged_refresh_pr_inputs_without_manual_authority_booleans():
    result = resolve(auth())
    kwargs = result.refresh_pr_kwargs(repository_root="/repo", invocation_id="invocation:1363", environment={"GITHUB_TOKEN": "redacted"})
    assert kwargs["authorization_id"] == result.authorization_id
    assert kwargs["authorization_current"] is True
    assert kwargs["branch_refresh_authorized"] is True
    assert kwargs["label_write_authorized"] is True
    assert kwargs["expected_head_sha"] == HEAD
    assert kwargs["current_main_sha"] == MAIN


def test_blocked_evidence_cannot_project_refresh_inputs():
    with pytest.raises(RuntimeError, match="applicable"):
        resolve().refresh_pr_kwargs(repository_root="/repo", invocation_id="x", environment={})
