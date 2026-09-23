"""Shared lifecycle-label admission fixtures for issue-label tests."""
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    AdmissionStatus,
    LifecycleMutationAdmissionResult,
)


def admitted_lifecycle_labels() -> LifecycleMutationAdmissionResult:
    return LifecycleMutationAdmissionResult(
        requested_mutation="replace-lifecycle-labels",
        admitted=True,
        status=AdmissionStatus.ADMITTED,
        reason_codes=(),
        details=(),
        authorization_id="lifecycle-authorization:test",
        snapshot_id="lifecycle-state-snapshot:test",
    )


def refused_lifecycle_labels() -> LifecycleMutationAdmissionResult:
    return LifecycleMutationAdmissionResult(
        requested_mutation="replace-lifecycle-labels",
        admitted=False,
        status=AdmissionStatus.BLOCKED,
        reason_codes=("authorization-not-authorized",),
        details=("authorization state is not authorized",),
        authorization_id="lifecycle-authorization:test",
        snapshot_id="lifecycle-state-snapshot:test",
    )
