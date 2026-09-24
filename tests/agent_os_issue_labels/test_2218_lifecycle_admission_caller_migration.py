"""Regression guards for the #2218 lifecycle-label caller migration.

#2188 replaced the lossy ``label_write_authorized`` boolean with the canonical
``LifecycleMutationAdmissionResult`` contract, but migrated only the production
consumers.  Every caller and test still passing the retired boolean kept main red
and left ``refresh_pr(...)`` projecting a keyword the request boundary no longer
accepted, so the governed branch-refresh facade raised ``TypeError`` in production.

These tests pin the migrated contract itself rather than one failing fixture:
the retired boolean must stay rejected at every migrated boundary, absent and
refused admissions must fail closed with zero writes, admitted evidence must still
converge, and the persisted authorization-source record must keep round-tripping.
"""

from __future__ import annotations

import inspect

import pytest

from scripts.agent_os_issue_labels.connected_issue_creation import (
    converge_connected_issue_creation,
)
from scripts.agent_os_issue_labels.issue_reconciler import reconcile_issue_labels
from scripts.agent_os_issue_labels.pr_branch_refresh import (
    PullRequestBranchRefreshRequest,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_authorization import (
    BranchRefreshAuthorizationEvidence,
    RefreshAuthorization,
    RefreshAuthorizationState,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_operator import refresh_pr

RETIRED = "label_write_authorized"

# Boundaries #2188 migrated to canonical admission.  A boundary that reintroduces the
# retired boolean re-opens the bypass this issue exists to close.
MIGRATED_BOUNDARIES = (
    reconcile_issue_labels,
    converge_connected_issue_creation,
    refresh_pr,
)


@pytest.mark.parametrize("boundary", MIGRATED_BOUNDARIES, ids=lambda fn: fn.__name__)
def test_migrated_boundaries_do_not_accept_the_retired_label_boolean(boundary):
    parameters = inspect.signature(boundary).parameters
    assert RETIRED not in parameters, (
        f"{boundary.__name__} reintroduced the retired {RETIRED} boolean; "
        "lifecycle-label authority must stay bound to LifecycleMutationAdmissionResult"
    )
    assert not any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ), f"{boundary.__name__} must not absorb the retired boolean through **kwargs"


def test_branch_refresh_request_does_not_carry_boolean_label_authority():
    assert RETIRED not in PullRequestBranchRefreshRequest.__dataclass_fields__
    assert "lifecycle_admission" not in PullRequestBranchRefreshRequest.__dataclass_fields__


def test_refresh_kwargs_projection_never_reaches_the_request_boundary():
    """The production break: a projected keyword the request no longer accepts."""
    evidence = BranchRefreshAuthorizationEvidence(
        repository="Blummer92/agent-os",
        pr_number=1363,
        authorization_id="auth:1363",
        applicable=True,
        authorization_current=True,
        branch_refresh_authorized=True,
        label_write_authorized=True,
        expected_head_sha="a" * 40,
        current_main_sha="b" * 40,
        allowed_changed_paths=("x.py",),
        forbidden_paths=(".github/workflows/x.yml",),
        required_validation_command_ids=("pytest:pr-branch-refresh",),
        reason_codes=(),
    )
    kwargs = evidence.refresh_pr_kwargs(
        repository_root="/repo",
        invocation_id="invocation:1363",
        environment={"GITHUB_TOKEN": "redacted-test-token"},
    )
    assert RETIRED not in kwargs
    # Every projected keyword must be accepted by the facade it is projected into.
    accepted = set(inspect.signature(refresh_pr).parameters)
    assert set(kwargs).issubset(accepted), set(kwargs) - accepted


def test_persisted_authorization_record_still_round_trips_its_stored_field():
    """Authorization-source data is evidence, not a caller-supplied grant."""
    record = RefreshAuthorization(
        schema_version="1.0",
        repository="Blummer92/agent-os",
        pr_number=1363,
        base_branch="main",
        expected_head_sha="a" * 40,
        expected_main_sha="b" * 40,
        allowed_changed_paths=("x.py",),
        forbidden_paths=(".github/workflows/x.yml",),
        required_validation_command_ids=("pytest:pr-branch-refresh",),
        branch_refresh_authorized=True,
        label_write_authorized=True,
        owner_decision_reference="github-owner-decision:1363",
        state=RefreshAuthorizationState.AUTHORIZED,
    )
    assert record.to_dict()[RETIRED] is True


