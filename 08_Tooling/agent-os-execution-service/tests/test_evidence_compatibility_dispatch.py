from __future__ import annotations

import pytest

from agent_os_execution_service.authorized_validation_entrypoint import (
    _require_dispatch_compatibility,
)
from scripts.agent_os_issue_acceptance.evidence_compatibility import (
    CompatibilityEvidenceRecord,
    CompatibilityOutcome,
    ExpectedGeneration,
    evaluate_execution_dispatch_compatibility,
    evaluate_ready_for_review_compatibility,
)


def _expected() -> ExpectedGeneration:
    return ExpectedGeneration(
        bindings=(
            ("repository", "Blummer92/agent-os"),
            ("issue_identity", "issue:1201"),
            ("authorization_id", "authorization:current"),
            ("scope_id", "scope:current"),
            ("head_sha", "b" * 40),
            ("environment_id", "environment:current"),
        )
    )


def _record(evidence_id: str, owner: str, **bindings: str) -> CompatibilityEvidenceRecord:
    return CompatibilityEvidenceRecord(
        evidence_id=evidence_id,
        owner=owner,
        bindings=tuple(bindings.items()),
    )


def test_dispatch_guard_accepts_only_compatible_execution_context() -> None:
    decision = evaluate_execution_dispatch_compatibility(
        expected=_expected(),
        records=(
            _record(
                "runtime:current",
                "runtime",
                repository="Blummer92/agent-os",
                head_sha="b" * 40,
                environment_id="environment:current",
            ),
        ),
    )
    assert decision.outcome is CompatibilityOutcome.COMPATIBLE
    assert _require_dispatch_compatibility(decision) is None


def test_dispatch_guard_blocks_old_environment_and_names_reacquisition_owner() -> None:
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
    with pytest.raises(RuntimeError, match="reacquire=environment"):
        _require_dispatch_compatibility(decision)


def test_dispatch_guard_blocks_authorization_drift_as_decision_boundary() -> None:
    decision = evaluate_execution_dispatch_compatibility(
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
    with pytest.raises(RuntimeError, match="needs-decision"):
        _require_dispatch_compatibility(decision)


def test_dispatch_guard_rejects_ready_for_review_context() -> None:
    decision = evaluate_ready_for_review_compatibility(
        expected=_expected(),
        records=(
            _record(
                "review:current",
                "review",
                repository="Blummer92/agent-os",
                head_sha="b" * 40,
            ),
        ),
    )
    with pytest.raises(ValueError, match="execution-dispatch"):
        _require_dispatch_compatibility(decision)
