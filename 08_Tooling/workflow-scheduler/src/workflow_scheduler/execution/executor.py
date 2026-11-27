"""Task executor with durable lease claims and guarded settlement."""

import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import copy, deepcopy
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional

from workflow_scheduler.adapters import TaskAdapter
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.execution.retry_manager import RetryManager
from workflow_scheduler.governance import StopConditionChecker
from workflow_scheduler.models import ApprovalDecision, ApprovalRequest, Task, TaskStatus
from workflow_scheduler.repository import SQLiteRepository
from workflow_scheduler.time_utils import utc_now


_CONTRACT_RESULT_STATUSES = frozenset({"success", "failure", "retryable", "blocked", "approval-required"})
_STORE_ERRORS = (sqlite3.Error, OSError)


def _is_contract_result(raw: Any) -> bool:
    """Use the five-state contract only if the documented legacy key is absent."""
    return isinstance(raw, dict) and "success" not in raw and "status" in raw


def _valid_retry_after(value: Any) -> bool:
    """Check that the adapter's delay can actually be scheduled."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value >= 0:
        return False
    try:
        utc_now() + timedelta(seconds=value)
    except (OverflowError, ValueError):
        return False
    return True


def _validate_contract_result(raw: Dict[str, Any]) -> Optional[str]:
    """Validate status, message and the conditional five-state fields."""
    status = raw.get("status")
    if not isinstance(status, str) or status not in _CONTRACT_RESULT_STATUSES:
        return "adapter contract result 'status' must be a supported string"
    message = raw.get("message")
    if not isinstance(message, str) or not message.strip():
        return "adapter contract result missing required non-empty string field 'message'"
    if status == "retryable" and not _valid_retry_after(raw.get("retry_after")):
        return "adapter contract result with status='retryable' requires a finite schedulable 'retry_after'"
    reason_field = {"blocked": "blocked_reason", "approval-required": "approval_reason"}.get(status)
    if reason_field is not None:
        reason = raw.get(reason_field)
        if not isinstance(reason, str) or not reason.strip():
            return f"adapter contract result with status='{status}' requires a non-empty string '{reason_field}'"
    return _validate_result_fields(raw, succeeded=status == "success")


def _validate_result_fields(raw: Dict[str, Any], *, succeeded: bool) -> Optional[str]:
    """Check common result fields before writing the task or its audit."""
    error = raw.get("error")
    if error is not None and not isinstance(error, str):
        return f"adapter result 'error' must be a string or None, got {type(error).__name__}"
    transient = raw.get("is_transient", False)
    if not isinstance(transient, bool):
        return f"adapter result 'is_transient' must be a bool, got {type(transient).__name__}"
    if succeeded and error is not None:
        return "successful adapter result cannot carry an error"
    if succeeded and transient:
        return "successful adapter result cannot be transient"
    output = raw.get("output")
    if output is not None:
        if not isinstance(output, dict):
            return "adapter result 'output' must be a dict or None"
        try:
            json.dumps(output, allow_nan=False)
        except (TypeError, ValueError, OverflowError, RecursionError):
            return "adapter result 'output' is not JSON serializable"
    return None


def _validate_adapter_result(raw: Any) -> Optional[str]:
    """Validate the result against its documented legacy or five-state shape."""
    if not isinstance(raw, dict):
        return f"adapter result must be a dict, got {type(raw).__name__}"
    if _is_contract_result(raw):
        return _validate_contract_result(raw)
    if "success" not in raw:
        return "adapter result missing required 'success' or 'status' key"
    if not isinstance(raw["success"], bool):
        return f"adapter result 'success' must be a bool, got {type(raw['success']).__name__}"
    return _validate_result_fields(raw, succeeded=raw["success"])


@dataclass
class ExecutionResult:
    """An independent task result; a failed result does not default to pass."""

    success: bool
    error: Optional[str]
    output: Optional[Dict[str, Any]]
    is_transient: bool = False
    status: Optional[str] = None
    blockers: Optional[list[str]] = None
    checks_passed: Optional[list[str]] = None
    checks_failed: Optional[list[str]] = None

    def __post_init__(self) -> None:
        if self.status is None:
            self.status = "pass" if self.success is True else "fail"
        self.output = deepcopy(self.output)
        self.blockers = list(self.blockers or ())
        self.checks_passed = list(self.checks_passed or ())
        self.checks_failed = list(self.checks_failed or ())


def _blocked(code: str, reason: str) -> ExecutionResult:
    return ExecutionResult(False, reason, None, status="blocked", blockers=[code], checks_failed=[code])


def _task_copy(task: Task) -> Task:
    """Stage a transition independently, retaining repository snapshot metadata."""
    staged = copy(task)
    staged.payload = deepcopy(task.payload)
    staged.depends_on = task.depends_on.copy()
    return staged


class Executor:
    """Execute and settle each task under one durable claim.

    In concurrent batches the caller must supply a concurrency-safe adapter
    and collaborators. Repository fencing, not interpreter locking, prevents
    simultaneous dispatch of the same task.
    """

    def __init__(
        self,
        adapter: TaskAdapter,
        repository: SQLiteRepository,
        audit_logger: AuditLogger,
        lease_timeout_seconds: int = 300,
        max_workers: int = 1,
    ):
        if type(max_workers) is not int or max_workers < 1:
            raise ValueError(f"max_workers must be >= 1, got {max_workers}")
        self.adapter = adapter
        self.repository = repository
        self.audit_logger = audit_logger
        self.lease_timeout_seconds = lease_timeout_seconds
        self.max_workers = max_workers

    def execute(self, task: Task, ownership_registry: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """Reconcile the caller snapshot, claim once, then execute and settle once."""
        try:
            current = self.repository.get_task(task.id)
            if not self._same_task(task, current):
                return self._task_state_conflict()
            if current.lease_lock is not None or current.status is TaskStatus.RUNNING:
                return self._lease_unavailable()
            snapshot = getattr(task, "_repository_snapshot", None)
            if snapshot is not None and current._repository_snapshot != snapshot:
                return self._task_state_conflict()
            if current.is_completed() or current.status is TaskStatus.PAUSED:
                return self._task_state_conflict()
            if getattr(task, "_require_running_workflow", False):
                current._require_running_workflow = True

            stop = StopConditionChecker.check_all_stop_conditions(
                task=current, ownership_registry=ownership_registry, source_of_truth_db=self.repository,
            )
            if stop.is_blocked:
                result = self._handle_preflight_block(current, stop)
                vars(task).update(vars(current))
                return result
            issue = self._audit(lambda: self.audit_logger.log_governance_check_passed(current))
            if issue is not None:
                return issue

            token, claimed = self._acquire_lease(current)
            if token is None:
                return self._lease_unavailable()
            if claimed is None:
                return self._task_state_conflict()
            result = self._execute_claimed(claimed, token)
            vars(task).update(vars(claimed))
            return result
        except _STORE_ERRORS:
            return self._task_state_conflict()

    @staticmethod
    def _same_task(task: Task, current: Optional[Task]) -> bool:
        return current is not None and (
            task.id, task.workflow_id, task.idempotency_key
        ) == (current.id, current.workflow_id, current.idempotency_key)

    @staticmethod
    def _lease_unavailable() -> ExecutionResult:
        return ExecutionResult(False, "Could not acquire execution lease", None,
                               is_transient=True, status="fail", checks_failed=["lease_acquisition"])

    def _handle_preflight_block(self, task, stop) -> ExecutionResult:
        next_task = _task_copy(task)
        blockers = stop.blockers
        if set(blockers) == {StopConditionChecker.APPROVAL_ENGINE_DEFERRED}:
            approval = self.repository.get_approval_request(task.id)
            if approval is not None and approval.decision is ApprovalDecision.REJECTED:
                return self._governance_block(task, None, blockers, "Task was rejected by approver")
            requested = None if approval is not None else ApprovalRequest(
                id=str(uuid.uuid4()), task_id=task.id, requested_by=task.owner,
                decision=ApprovalDecision.PENDING,
            )
            next_task.mark_approval_pending()
            result = _blocked(StopConditionChecker.APPROVAL_ENGINE_DEFERRED,
                              "Task requires explicit approval before execution")
            audit = (lambda: self.audit_logger.log_approval_requested(task)) if requested else None
            return self._settle(task, next_task, None, result, audit, approval_request=requested)
        return self._governance_block(task, None, blockers, stop.reason)

    def _execute_claimed(self, task: Task, token: str) -> ExecutionResult:
        """Run the adapter on detached input, then apply a validated outcome."""
        try:
            raw = self.adapter.execute(replace(task))
            problem = _validate_adapter_result(raw)
        except Exception as exc:  # No adapter exception text in responses or durable errors.
            problem = f"adapter raised {type(exc).__name__}"
        if problem is not None:
            return self._fail(task, token, f"Invalid adapter result: {problem}", invalid=problem)
        if _is_contract_result(raw):
            return self._handle_contract_result(task, token, raw)
        if raw["success"]:
            return self._complete(task, token, raw.get("output"))

        error = raw.get("error") or "Unknown error"
        transient = raw.get("is_transient", False)
        if transient and RetryManager.should_retry(task):
            return self._retry(task, token, error, RetryManager.compute_delay(task.retry_count))
        return self._fail(task, token, error, exhausted=transient)

    def execute_many(
        self,
        tasks: List[Task],
        ownership_registry: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, ExecutionResult]:
        """Execute independent, unique task IDs; an empty batch has no outcomes."""
        if not tasks:
            return {}
        if len({task.id for task in tasks}) != len(tasks):
            raise ValueError("Cannot execute a batch containing a duplicate task id")
        if self.max_workers == 1:
            return {task.id: self._execute_one(task, ownership_registry) for task in tasks}

        results: Dict[str, ExecutionResult] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_task_id = {
                pool.submit(self._execute_one, task, ownership_registry): task.id for task in tasks
            }
            for future in as_completed(future_to_task_id):
                results[future_to_task_id[future]] = future.result()
        return results

    def _execute_one(self, task: Task, ownership_registry: Optional[Dict[str, Any]]) -> ExecutionResult:
        """Contain unexpected per-task exceptions; do not retry or release its claim."""
        try:
            return self.execute(task, ownership_registry)
        except Exception:
            return _blocked("executor_error", "Task execution could not be reconciled")

    def _handle_contract_result(self, task: Task, token: str, result: Dict[str, Any]) -> ExecutionResult:
        """Route the five-state result through the same guarded settlement as legacy results."""
        status, message = result["status"], result["message"]
        if status == "success":
            return self._complete(task, token, result.get("output"))
        if status == "retryable":
            if RetryManager.should_retry(task):
                return self._retry(task, token, message, result["retry_after"])
            return self._fail(task, token, message, exhausted=True)
        if status == "blocked":
            return self._governance_block(task, token, ["adapter_blocked"], result["blocked_reason"])
        if status == "approval-required":
            return self._defer(task, token, result["approval_reason"])
        return self._fail(task, token, message)

    def _complete(self, task, token, output) -> ExecutionResult:
        output = deepcopy(output)
        next_task = _task_copy(task)
        next_task.mark_completed(result=output)
        return self._settle(
            task, next_task, token, ExecutionResult(True, None, output, checks_passed=["execution"]),
            lambda: self.audit_logger.log_task_completed(task, result=deepcopy(output)),
        )

    def _retry(self, task, token, error, delay) -> ExecutionResult:
        next_task = _task_copy(task)
        next_task.mark_failed(error=error, is_transient=True)
        next_task.schedule_retry(delay)
        return self._settle(
            task, next_task, token,
            ExecutionResult(False, error, None, True, "retry_scheduled", checks_failed=["execution"]),
            lambda: self.audit_logger.log_retry_scheduled(next_task, delay_seconds=delay),
        )

    def _fail(self, task, token, error, *, exhausted=False, invalid=None) -> ExecutionResult:
        next_task = _task_copy(task)
        next_task.mark_failed(error=error, is_transient=False)

        def audit():
            if invalid is not None:
                self.audit_logger.log_adapter_result_invalid(task, reason=invalid)
            else:
                if exhausted:
                    self.audit_logger.log_retry_exhausted(task, attempts=task.retry_count)
                self.audit_logger.log_task_failed(task, error=error, is_transient=False)

        result = ExecutionResult(False, error, None,
                                 checks_failed=["execution" if invalid is None else "adapter_result_invalid"])
        return self._settle(task, next_task, token, result, audit)

    def _governance_block(self, task, token, blockers, reason) -> ExecutionResult:
        # Task does not expose a governance-block transition or in-memory
        # history. The executor owns this transition and emits the durable audit.
        next_task = _task_copy(task)
        next_task.status = TaskStatus.GOVERNANCE_BLOCKED
        next_task.updated_at = utc_now()
        return self._settle(
            task, next_task, token,
            ExecutionResult(False, reason, None, status="blocked", blockers=blockers, checks_failed=blockers),
            lambda: self.audit_logger.log_governance_blocked(task, blockers=blockers, reason=reason),
        )

    def _defer(self, task, token, reason) -> ExecutionResult:
        if self.repository.get_approval_request(task.id) is not None:
            # Task-ID-only approval cannot distinguish a new request from a
            # delayed replay. Preserve the first request regardless of decision.
            return self._governance_block(
                task, token, ["adapter_approval_repeated"],
                "Adapter requested another approval for an already reviewed task",
            )
        next_task = _task_copy(task)
        next_task.approval_required = True
        next_task.mark_approval_pending()
        approval = ApprovalRequest(
            id=str(uuid.uuid4()), task_id=task.id, requested_by=task.owner,
            decision=ApprovalDecision.PENDING, reason=reason,
        )
        return self._settle(
            task, next_task, token, _blocked("adapter_approval_required", reason),
            lambda: self.audit_logger.log_approval_requested(task), approval_request=approval,
        )

    @staticmethod
    def _task_state_conflict() -> ExecutionResult:
        return _blocked("task_state_conflict", "Task state could not be reconciled; no outcome confirmed")

    @staticmethod
    def _audit(write: Callable[[], None]) -> Optional[ExecutionResult]:
        try:
            write()
        except Exception:
            return _blocked("audit_persistence_failed", "Task audit could not be confirmed")
        return None

    def _settle(self, task, next_task, token, outcome, audit, *, approval_request=None) -> ExecutionResult:
        """Accept settlement before outcome audit; never publish a speculative transition."""
        if not self._persist_task(next_task, token, approval_request=approval_request):
            return self._task_state_conflict()
        issue = self._audit(audit) if audit is not None else None
        vars(task).update(vars(next_task))
        return issue if issue is not None else outcome

    def _persist_task(self, task: Task, token: Optional[str], *, approval_request=None) -> bool:
        """Only literal True proves settlement. The repository owns durable claim release."""
        kwargs = {"approval_request": approval_request} if approval_request is not None else {}
        try:
            if token is None:
                persisted = self.repository.update_task(task, **kwargs)
            else:
                persisted = self.repository.update_claimed_task(task, token, **kwargs)
        except _STORE_ERRORS:
            return False
        if persisted is not True:
            return False
        if token is not None and task.status is not TaskStatus.RUNNING:
            task.release_lease()
        return True

    def _acquire_lease(self, task: Task) -> tuple[Optional[str], Optional[Task]]:
        """Return one claim and fresh row; lack of readback never permits release."""
        token = self.repository.try_claim_execution(
            task.id, require_running_workflow=getattr(task, "_require_running_workflow", False),
            snapshot=task._repository_snapshot,
        )
        if type(token) is not str or not token.strip():
            return None, None
        claimed = self.repository.get_task(task.id)
        if (not self._same_task(task, claimed) or claimed.status is not TaskStatus.RUNNING
                or claimed.lease_lock is None):
            return token, None
        if getattr(task, "_require_running_workflow", False):
            claimed._require_running_workflow = True
        return token, claimed
