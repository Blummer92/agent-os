"""Governance stop conditions for task execution."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from workflow_scheduler.models import ApprovalDecision, Task, TaskMode


@dataclass
class StopConditionResult:
    """Result of checking stop conditions."""

    is_blocked: bool
    blockers: List[str] = field(default_factory=list)
    reason: str = ""


class StopConditionChecker:
    """Enforces five governance stop conditions before task execution."""

    # Stop condition: Production/approval_required tasks await an explicit
    # human decision recorded as an APPROVED ApprovalRequest.
    APPROVAL_ENGINE_DEFERRED = "approval_engine_deferred"

    # Stop condition: Task target is ambiguous
    AMBIGUOUS_TARGET = "ambiguous_target"

    # Stop condition: Missing write authorization
    MISSING_AUTHORIZATION = "missing_authorization"

    # Stop condition: Conflicting source-of-truth
    CONFLICTING_SOURCE_OF_TRUTH = "conflicting_source_of_truth"

    # Stop condition: Governed field risk
    GOVERNED_FIELD_RISK = "governed_field_risk"

    @staticmethod
    def _requires_approval(task: Task) -> bool:
        """Return True when a task needs an explicit human decision before it runs."""
        return bool(
            task.mode == TaskMode.PRODUCTION or task.production_ready or task.approval_required
        )

    @staticmethod
    def _lookup_approval(task_id: str, source_of_truth_db: Optional[Any]) -> Optional[Any]:
        """Return the most recent ApprovalRequest for a task, or None.

        Tolerates a source_of_truth_db that predates the approval engine (or a
        test double that only implements ``has_conflict``) by treating a missing
        ``get_approval_request`` as "no approval on record".
        """
        if source_of_truth_db is None:
            return None

        getter = getattr(source_of_truth_db, "get_approval_request", None)
        if getter is None:
            return None

        return getter(task_id)

    @staticmethod
    def _is_approved(task_id: str, source_of_truth_db: Optional[Any]) -> bool:
        """Return True only when an explicit APPROVED record exists for the task.

        Absence of a record is never approval: with no approval store wired in,
        every governed task stays blocked until a human decision is recorded.
        """
        approval = StopConditionChecker._lookup_approval(task_id, source_of_truth_db)
        return approval is not None and approval.decision == ApprovalDecision.APPROVED

    @staticmethod
    def check_all_stop_conditions(
        task: Task,
        ownership_registry: Optional[Dict[str, Any]] = None,
        source_of_truth_db: Optional[Any] = None,
    ) -> StopConditionResult:
        """Check all stop conditions for a task.

        Args:
            task: Task to check
            ownership_registry: Registry mapping agents to owned systems (optional)
            source_of_truth_db: Database for checking conflicts (optional)

        Returns:
            StopConditionResult with blockers list if any stop condition triggered
        """
        blockers: List[str] = []

        # Stop Condition 1: Approval Engine Deferred
        # Block Production-mode tasks, production_ready flag, or approval_required
        # unless an explicit ApprovalRequest for this task has been APPROVED.
        if StopConditionChecker._requires_approval(task) and not StopConditionChecker._is_approved(
            task.id, source_of_truth_db
        ):
            blockers.append(StopConditionChecker.APPROVAL_ENGINE_DEFERRED)

        # Stop Condition 2: Ambiguous Target
        # If task.action is not clearly defined, block it
        if not task.action or task.action.strip() == "":
            blockers.append(StopConditionChecker.AMBIGUOUS_TARGET)

        # Stop Condition 3: Missing Authorization
        # If ownership registry is provided, check write authorization
        if ownership_registry:
            owned_systems = ownership_registry.get(task.owner, {}).get("owned_systems", [])
            if task.action not in owned_systems and not task.action.startswith("read:"):
                blockers.append(StopConditionChecker.MISSING_AUTHORIZATION)

        # Stop Condition 4: Conflicting Source-of-Truth
        # If source_of_truth_db is provided, check for conflicts
        if source_of_truth_db:
            if hasattr(source_of_truth_db, "has_conflict") and source_of_truth_db.has_conflict(task.id):
                blockers.append(StopConditionChecker.CONFLICTING_SOURCE_OF_TRUTH)

        # Stop Condition 5: Governed Field Risk
        # Block if task payload indicates writing to governed fields without approval
        if task.payload.get("governed_field_risk") or task.payload.get("writes_governed_field"):
            blockers.append(StopConditionChecker.GOVERNED_FIELD_RISK)

        if blockers:
            return StopConditionResult(
                is_blocked=True,
                blockers=blockers,
                reason=f"Task execution blocked by stop conditions: {', '.join(blockers)}",
            )

        return StopConditionResult(is_blocked=False)

    @staticmethod
    def check_approval_required(
        task: Task, source_of_truth_db: Optional[Any] = None
    ) -> StopConditionResult:
        """Check the approval_required flag against the approval engine.

        Pass ``source_of_truth_db`` to clear the block with a recorded APPROVED
        decision. Called without one, the task stays blocked -- there is nowhere
        to read an approval from, so there is no approval.
        """
        if task.approval_required and not StopConditionChecker._is_approved(
            task.id, source_of_truth_db
        ):
            return StopConditionResult(
                is_blocked=True,
                blockers=[StopConditionChecker.APPROVAL_ENGINE_DEFERRED],
                reason="Task requires approval; awaiting an APPROVED decision",
            )
        return StopConditionResult(is_blocked=False)

    @staticmethod
    def check_production_mode(
        task: Task, source_of_truth_db: Optional[Any] = None
    ) -> StopConditionResult:
        """Check production targeting against the approval engine.

        Covers both the ``production_ready`` flag and ``TaskMode.PRODUCTION``, so
        this helper agrees with ``check_all_stop_conditions`` rather than letting
        a Production-mode task past a check that only read the flag.
        """
        if (
            task.production_ready or task.mode == TaskMode.PRODUCTION
        ) and not StopConditionChecker._is_approved(task.id, source_of_truth_db):
            return StopConditionResult(
                is_blocked=True,
                blockers=[StopConditionChecker.APPROVAL_ENGINE_DEFERRED],
                reason="Task targets production; awaiting an APPROVED decision",
            )
        return StopConditionResult(is_blocked=False)
