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
from scripts.agent_os_issue_labels.connected_pr_lifecycle import (
    converge_connected_pull_request_lifecycle,
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
from scripts.agent_os_issue_labels.pr_lifecycle import reconcile_pull_request_lifecycle
from scripts.agent_os_issue_labels.pr_reconciler import reconcile_pull_request_labels
from tests.agent_os_issue_labels.lifecycle_admission import (
    admitted_lifecycle_labels,
    refused_lifecycle_labels,
)
from tests.agent_os_issue_labels.test_pr_reconciler import FakeProvider, snap

RETIRED = "label_write_authorized"

# Boundaries #2188 migrated to canonical admission.  A boundary that reintroduces the
# retired boolean re-opens the bypass this issue exists to close.
MIGRATED_BOUNDARIES = (
    reconcile_issue_labels,
    reconcile_pull_request_labels,
    reconcile_pull_request_lifecycle,
    converge_connected_issue_creation,
    converge_connected_pull_request_lifecycle,
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
    assert "lifecycle_admission" in PullRequestBranchRefreshRequest.__dataclass_fields__


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


def _reconcile(provider, admission):
    return reconcile_pull_request_labels(
        provider,
        "Blummer92/agent-os",
        1023,
        dry_run=False,
        lifecycle_admission=admission,
    )


def test_absent_admission_fails_closed_with_zero_writes():
    provider = FakeProvider([snap()])
    result = _reconcile(provider, None)
    assert result.reason_codes == ("lifecycle-admission-required",)
    assert not provider.added and not provider.removed
    assert result.side_effects_performed is False


def test_refused_admission_fails_closed_with_zero_writes():
    provider = FakeProvider([snap()])
    result = _reconcile(provider, refused_lifecycle_labels())
    assert result.convergence_status == "blocked"
    assert not provider.added and not provider.removed
    assert result.side_effects_performed is False


@pytest.mark.parametrize(
    "impostor",
    [
        True,
        "admitted",
        {"admitted": True, "status": "admitted"},
        type("FakeAdmission", (), {"admitted": True})(),
    ],
    ids=["bare-true", "string", "mapping", "duck-typed-object"],
)
def test_non_canonical_admission_evidence_never_grants_write_authority(impostor):
    """A truthy stand-in must not be upgraded into lifecycle authority."""
    provider = FakeProvider([snap()])
    result = _reconcile(provider, impostor)
    assert result.convergence_status == "blocked"
    assert not provider.added and not provider.removed


def test_admitted_admission_still_permits_intended_convergence():
    labels = (
        "pr:ready-for-review",
        "validation:failing",
        "branch:behind",
        "review:needs-attention",
        "human:keep",
    )
    provider = FakeProvider([snap(labels=labels)] * 3)
    result = _reconcile(provider, admitted_lifecycle_labels())
    assert result.convergence_status == "converged"
    assert "human:keep" in provider.labels


def test_repeated_admitted_invocation_is_idempotent():
    labels = ("pr:draft", "validation:pending", "branch:current", "review:clear")
    provider = FakeProvider([snap(labels=labels)] * 6)
    first = _reconcile(provider, admitted_lifecycle_labels())
    second = _reconcile(provider, admitted_lifecycle_labels())
    assert first.convergence_status == "converged"
    assert second.convergence_status == "converged"
    assert not provider.added and not provider.removed


def test_dry_run_never_writes_even_with_admitted_evidence():
    provider = FakeProvider([snap()])
    result = reconcile_pull_request_labels(
        provider,
        "Blummer92/agent-os",
        1023,
        dry_run=True,
        lifecycle_admission=admitted_lifecycle_labels(),
    )
    assert result.convergence_status == "dry-run"
    assert not provider.added and not provider.removed
