"""#1201 fail-closed Ready-for-Review compatibility consumer seam.

This module deliberately wraps the existing lifecycle reconciliation projection
without changing IssueOperationalState or lifecycle reconciliation semantics.
The compatibility decision is evidence, never authority.
"""

from __future__ import annotations

from .evidence_compatibility import (
    CompatibilityContext,
    CompatibilityOutcome,
    EvidenceCompatibilityDecision,
)
from .lifecycle_reconciliation import (
    LifecycleReconciliationInput,
    LifecycleReconciliationResult,
    reconcile_lifecycle,
)


def reconcile_ready_for_review(
    evidence: LifecycleReconciliationInput,
    *,
    compatibility_decision: EvidenceCompatibilityDecision,
) -> LifecycleReconciliationResult:
    """Reconcile lifecycle only when supplied RfR evidence is one generation.

    A non-compatible decision stops before lifecycle reconciliation can derive a
    Ready-for-Review-consistent result. Reacquisition and manual decisions remain
    owned by their canonical contracts; this seam performs neither.
    """

    if type(evidence) is not LifecycleReconciliationInput:
        raise TypeError("evidence must be exact LifecycleReconciliationInput")
    if type(compatibility_decision) is not EvidenceCompatibilityDecision:
        raise TypeError(
            "compatibility_decision must be exact EvidenceCompatibilityDecision"
        )
    if compatibility_decision.context is not CompatibilityContext.READY_FOR_REVIEW:
        raise ValueError("compatibility_decision must use ready-for-review context")
    if compatibility_decision.outcome is not CompatibilityOutcome.COMPATIBLE:
        reasons = ",".join(compatibility_decision.reason_codes)
        owners = ",".join(compatibility_decision.reacquire_owners) or "none"
        raise RuntimeError(
            "Ready-for-Review reconciliation blocked by evidence compatibility: "
            f"outcome={compatibility_decision.outcome.value}; reasons={reasons}; "
            f"reacquire={owners}; decision={compatibility_decision.decision_id}"
        )
    return reconcile_lifecycle(evidence)
