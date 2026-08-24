from __future__ import annotations

import pytest

from scripts.agent_os_issue_acceptance.evidence_compatibility import (
    CompatibilityEvidenceRecord,
    CompatibilityOutcome,
    ExpectedGeneration,
    evaluate_execution_dispatch_compatibility,
    evaluate_ready_for_review_compatibility,
)
from scripts.agent_os_issue_acceptance.ready_for_review_compatibility import (
    reconcile_ready_for_review,
)
from scripts.agent_os_issue_acceptance.lifecycle_reconciliation import (
    LifecycleReconciliationInput,
)


def _expected(**overrides: str) -> ExpectedGeneration:
    values = {
        "repository": "Blummer92/agent-os",
        "issue_identity": "issue:1201",
        "authorization_id": "authorization:current",
        "scope_id": "scope:current",
        "head_sha": "b" * 40,
        "environment_id": "environment:current",
        "lifecycle_snapshot_id": "lifecycle:current",
    }
    values.update(overrides)
    return ExpectedGeneration(bindings=tuple(values.items()))


def _record(evidence_id: str, owner: str, **bindings: str) -> CompatibilityEvidenceRecord:
    return CompatibilityEvidenceRecord(
        evidence_id=evidence_id,
        owner=owner,
        bindings=tuple(bindings.items()),
    )


def test_decision_retains_current_expected_bindings_for_consumer_diagnostics() -> None:
    decision = evaluate_execution_dispatch_compatibility(
        expected=_expected(),
        records=(
            _record(
                "runtime:current",
                "runtime",
                repository="Blummer92/agent-os",
                head_sha="b" * 40,
            ),
        ),
    )
    assert decision.outcome is CompatibilityOutcome.COMPATIBLE
    assert dict(decision.expected_bindings)["head_sha"] == "b" * 40
    assert decision.authority_created is False
    assert decision.side_effects_performed is False


def test_ready_for_review_consumer_rejects_old_review_before_reconciliation() -> None:
    decision = evaluate_ready_for_review_compatibility(
        expected=_expected(),
        records=(
            _record("validation:current", "validation", head_sha="b" * 40),
            _record("review:old", "review", head_sha="c" * 40),
        ),
    )
    assert decision.outcome is CompatibilityOutcome.REACQUIRE_REQUIRED
    with pytest.raises(RuntimeError, match="reacquire=review"):
        reconcile_ready_for_review(
            object(),  # type validation occurs before any lifecycle work
            compatibility_decision=decision,
        )


def test_ready_for_review_consumer_rejects_authorization_drift() -> None:
    decision = evaluate_ready_for_review_compatibility(
        expected=_expected(),
        records=(
            _record(
                "authorization:old",
                "authorization",
                authorization_id="authorization:old",
            ),
        ),
    )
    assert decision.outcome is CompatibilityOutcome.NEEDS_DECISION
    assert decision.reacquire_owners == ()


def test_execution_dispatch_consumer_diagnostic_names_smallest_owner() -> None:
    decision = evaluate_execution_dispatch_compatibility(
        expected=_expected(),
        records=(
            _record(
                "environment:old",
                "environment",
                environment_id="environment:old",
            ),
        ),
    )
    assert decision.outcome is CompatibilityOutcome.REACQUIRE_REQUIRED
    assert decision.reacquire_owners == ("environment",)


def test_compatible_ready_for_review_decision_does_not_create_authority() -> None:
    decision = evaluate_ready_for_review_compatibility(
        expected=_expected(),
        records=(
            _record(
                "review:current",
                "review",
                repository="Blummer92/agent-os",
                head_sha="b" * 40,
                lifecycle_snapshot_id="lifecycle:current",
            ),
        ),
    )
    assert decision.outcome is CompatibilityOutcome.COMPATIBLE
    assert decision.authority_created is False
    assert decision.side_effects_performed is False
