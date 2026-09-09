"""Construct the existing content-bound lifecycle authorization from owner decision evidence.

This module is a pure producer for ``LifecycleMutationAuthorization``.  It does not
infer authority, perform I/O, or create a second authorization model.  Callers
must supply a distinct, already-recorded owner decision identity and the exact
current lifecycle snapshot to which that decision applies.
"""
from __future__ import annotations

from dataclasses import dataclass

from .lifecycle_mutation_guard import (
    MUTATIONS,
    SCHEMA_VERSION,
    LifecycleMutationAuthorization,
    LifecycleStateSnapshot,
)


@dataclass(frozen=True, slots=True)
class LifecycleOwnerDecision:
    """Non-authorizing decision evidence supplied by the canonical request path."""

    repository: str
    issue_number: int
    requested_mutations: tuple[str, ...]
    authorizer_id: str
    decision_id: str
    decision_recorded: bool

    def __post_init__(self) -> None:
        if type(self.repository) is not str or not self.repository:
            raise TypeError("repository must be a non-empty built-in string")
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise TypeError("issue_number must be a positive built-in integer")
        if type(self.requested_mutations) is not tuple or not self.requested_mutations:
            raise TypeError("requested_mutations must be a non-empty exact tuple")
        if len(set(self.requested_mutations)) != len(self.requested_mutations):
            raise ValueError("requested_mutations contains duplicates")
        if any(type(item) is not str or item not in MUTATIONS for item in self.requested_mutations):
            raise ValueError("requested_mutations contains an unsupported mutation")
        if type(self.authorizer_id) is not str or not self.authorizer_id:
            raise TypeError("authorizer_id must be a non-empty built-in string")
        if type(self.decision_id) is not str or not self.decision_id:
            raise TypeError("decision_id must be a non-empty built-in string")
        if type(self.decision_recorded) is not bool:
            raise TypeError("decision_recorded must be a built-in bool")


def produce_lifecycle_mutation_authorization(
    decision: LifecycleOwnerDecision,
    snapshot: LifecycleStateSnapshot,
) -> LifecycleMutationAuthorization:
    """Bind one explicit owner decision to the exact current lifecycle snapshot.

    Absence of a recorded decision fails closed.  Ordinary Safe Implementation
    Lane work therefore cannot synthesize closure authority by calling this
    producer without distinct owner-decision evidence.
    """
    if type(decision) is not LifecycleOwnerDecision:
        raise TypeError("decision must be LifecycleOwnerDecision")
    if type(snapshot) is not LifecycleStateSnapshot:
        raise TypeError("snapshot must be LifecycleStateSnapshot")
    if not decision.decision_recorded:
        raise PermissionError("a recorded owner decision is required")
    if decision.repository != snapshot.repository:
        raise ValueError("owner decision repository does not match lifecycle snapshot")
    if decision.issue_number != snapshot.issue_number:
        raise ValueError("owner decision issue does not match lifecycle snapshot")

    return LifecycleMutationAuthorization(
        schema_version=SCHEMA_VERSION,
        repository=snapshot.repository,
        issue_number=snapshot.issue_number,
        pull_request_number=snapshot.pull_request_number,
        authorized_mutations=decision.requested_mutations,
        expected_source_head=snapshot.source_head,
        expected_base_head=snapshot.base_head,
        expected_pr_state=snapshot.pr_state,
        expected_merged=snapshot.merged,
        expected_issue_state=snapshot.issue_state,
        expected_review_state=snapshot.review_state,
        expected_unresolved_threads=snapshot.unresolved_threads,
        expected_lifecycle_labels=snapshot.lifecycle_labels,
        observed_at_revision=snapshot.observed_revision,
        state="authorized",
        authorizer_id=decision.authorizer_id,
        decision_id=decision.decision_id,
    )
