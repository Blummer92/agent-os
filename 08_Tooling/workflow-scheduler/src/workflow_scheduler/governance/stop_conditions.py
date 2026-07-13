"""Governance stop conditions for task execution."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from workflow_scheduler.models import ApprovalDecision, Task, TaskStatus


@dataclass
class StopConditionResult:
    """Result of checking stop conditions."""

    is_blocked: bool
    blockers: List[str] = field(default_factory=list)
    reason: str = ""


class StopConditionChecker:
    """Enforces five governance stop conditions before task execution."""

    # Stop condition: Production/approval_required tasks deferred to Phase 2
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
        from workflow_scheduler.models import TaskMode

        if task.mode == TaskMode.PRODUCTION or task.production_ready or task.approval_required:
            approval = None
            if source_of_truth_db is not None and hasattr(source_of_truth_db, "get_approval_request"):
                approval = source_of_truth_db.get_approval_request(task.id)

            if approval is None or approval.decision != ApprovalDecision.APPROVED:
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
    def check_approval_required(task: Task) -> StopConditionResult:
        """Check if task requires approval (Phase 2 feature)."""
        if task.approval_required:
            return StopConditionResult(
                is_blocked=True,
                blockers=[StopConditionChecker.APPROVAL_ENGINE_DEFERRED],
                reason="Task requires approval; approval engine not yet implemented (Phase 2)",
            )
        return StopConditionResult(is_blocked=False)

    @staticmethod
    def check_production_mode(task: Task) -> StopConditionResult:
        """Check if task is marked for production (Phase 2 feature)."""
        if task.production_ready:
            return StopConditionResult(
                is_blocked=True,
                blockers=[StopConditionChecker.APPROVAL_ENGINE_DEFERRED],
                reason="Task marked for production; production mode not yet implemented (Phase 2)",
            )
        return StopConditionResult(is_blocked=False)
