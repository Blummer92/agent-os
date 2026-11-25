"""Pure workflow-plan state and transition checks; no execution or persistence."""

from collections import deque
from collections.abc import Callable, Collection
from copy import deepcopy
from dataclasses import InitVar, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from workflow_scheduler.time_utils import utc_now


class WorkflowStatus(str, Enum):
    """Lifecycle status, serialized as lowercase wire values."""

    DRAFT = "draft"
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    GOVERNANCE_BLOCKED = "governance_blocked"


class WorkflowMode(str, Enum):
    """Independent execution mode; title case is retained for stored plans."""

    DRAFT = "Draft"
    GATE = "Gate"
    PRODUCTION = "Production"


_TRANSITIONS = {
    WorkflowStatus.DRAFT: frozenset({
        WorkflowStatus.PENDING, WorkflowStatus.RUNNING, WorkflowStatus.PAUSED, WorkflowStatus.CANCELLED,
    }),
    WorkflowStatus.PENDING: frozenset({
        WorkflowStatus.RUNNING, WorkflowStatus.PAUSED, WorkflowStatus.CANCELLED,
    }),
    WorkflowStatus.RUNNING: frozenset({
        WorkflowStatus.PAUSED, WorkflowStatus.COMPLETED, WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED, WorkflowStatus.GOVERNANCE_BLOCKED,
    }),
    WorkflowStatus.PAUSED: frozenset({WorkflowStatus.RUNNING, WorkflowStatus.CANCELLED}),
}
_GUARDED_FIELDS = frozenset({"status", "tasks", "dependencies", "mode", "metadata"})
_MAX_TRANSITIONS = 64
_MAX_REASON = 500


@dataclass(frozen=True)
class WorkflowTransition:
    previous: WorkflowStatus
    current: WorkflowStatus
    at: datetime
    reason: str


def _require_nonblank(value: str, name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")


def _validate_graph(tasks: list[str], dependencies: dict[str, list[str]]) -> None:
    for task in tasks:
        _require_nonblank(task, "task ID")
    indegree = dict.fromkeys(tasks, 0)
    if len(indegree) != len(tasks):
        raise ValueError("duplicate task ID")
    dependents: dict[str, list[str]] = {task: [] for task in tasks}
    for task, required in dependencies.items():
        _require_nonblank(task, "task ID")
        if task not in indegree:
            raise ValueError("dependency owner is not in the plan")
        if type(required) is not list:
            raise TypeError("dependencies must be lists of task IDs")
        seen: set[str] = set()
        for parent in required:
            _require_nonblank(parent, "dependency task ID")
            if parent == task:
                raise ValueError("a task cannot depend on itself")
            if parent not in indegree:
                raise ValueError("dependency task is not in the plan")
            if parent in seen:
                raise ValueError("duplicate dependency task")
            seen.add(parent)
            dependents[parent].append(task)
        indegree[task] = len(seen)
    ready = [task for task in indegree if not indegree[task]]
    visited = 0
    while ready:
        visited += 1
        for dependent in dependents[ready.pop()]:
            indegree[dependent] -= 1
            if not indegree[dependent]:
                ready.append(dependent)
    if visited != len(tasks):
        raise ValueError("Circular dependency detected")


@dataclass
class WorkflowPlan:
    """Collection of dependent tasks forming a workflow.

    Mode and lifecycle status are separate axes: a Production plan starts
    in DRAFT, and a Draft-mode run may finish. The constructor restores
    persisted statuses; it is not proof that a workflow ran. Graph views are
    detached; use add_task/set_dependencies to edit the plan. Existing
    repository callers still own free-form metadata and persisted timestamps.
    """

    workflow_id: str
    title: str
    created_by: str
    mode: WorkflowMode = WorkflowMode.DRAFT
    status: WorkflowStatus = WorkflowStatus.DRAFT
    tasks: list[str] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    clock: InitVar[Callable[[], datetime] | None] = field(default=None, kw_only=True)

    def __post_init__(self, clock: Callable[[], datetime] | None) -> None:
        _require_nonblank(self.workflow_id, "workflow ID")
        _require_nonblank(self.title, "title")
        _require_nonblank(self.created_by, "created_by")
        if type(self.mode) is not WorkflowMode or type(self.status) is not WorkflowStatus:
            raise TypeError("mode and status must use their workflow enums")
        if type(self.tasks) is not list or type(self.dependencies) is not dict or type(self.metadata) is not dict:
            raise TypeError("plan tasks, dependencies and metadata must be a list, dict and dict")
        _validate_graph(self.tasks, self.dependencies)
        self.tasks = self.tasks.copy()
        self.dependencies = {task: deps.copy() for task, deps in self.dependencies.items()}
        self.metadata = deepcopy(self.metadata)
        self._clock = utc_now if clock is None else clock
        self.created_at = self._timestamp(self.created_at)
        self.updated_at = self.created_at if self.updated_at is None else self._timestamp(self.updated_at)
        self._history: deque[WorkflowTransition] = deque(maxlen=_MAX_TRANSITIONS)

    def __setattr__(self, name: str, value: object) -> None:
        if name in _GUARDED_FIELDS and "_history" in self.__dict__:
            raise AttributeError(f"workflow {name} cannot be assigned directly")
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if name in _GUARDED_FIELDS:
            raise AttributeError(f"workflow {name} cannot be deleted")
        super().__delattr__(name)

    def __getattribute__(self, name: str):
        value = super().__getattribute__(name)
        if name == "tasks" and "_history" in self.__dict__:
            return value.copy()
        if name == "dependencies" and "_history" in self.__dict__:
            return {task: deps.copy() for task, deps in value.items()}
        return value

    @property
    def transition_history(self) -> tuple[WorkflowTransition, ...]:
        """Bounded in-memory history. Durable audit events are owned elsewhere."""
        return tuple(self._history)

    def _timestamp(self, at: datetime | None) -> datetime:
        value = self._clock() if at is None else at
        if not isinstance(value, datetime):
            raise TypeError("workflow timestamp must be a datetime")
        return value

    def _require_editable_graph(self) -> None:
        if self.is_terminal():
            raise ValueError("terminal workflow graph cannot be edited")

    def add_task(self, task_id: str, *, at: datetime | None = None) -> None:
        self._require_editable_graph()
        _require_nonblank(task_id, "task ID")
        tasks = object.__getattribute__(self, "tasks")
        if task_id not in tasks:
            stamp = self._timestamp(at)
            tasks.append(task_id)
            self.updated_at = stamp

    def set_dependencies(self, task_id: str, depends_on: list[str], *, at: datetime | None = None) -> None:
        self._require_editable_graph()
        _require_nonblank(task_id, "task ID")
        candidate = self.dependencies
        candidate[task_id] = depends_on
        _validate_graph(self.tasks, candidate)
        stamp = self._timestamp(at)
        candidate[task_id] = depends_on.copy()
        object.__setattr__(self, "dependencies", candidate)
        self.updated_at = stamp

    def _transition(self, target: WorkflowStatus, *, at: datetime | None, reason: str = "") -> None:
        if type(target) is not WorkflowStatus or type(self.status) is not WorkflowStatus:
            raise TypeError("transition requires a workflow status enum")
        if target not in _TRANSITIONS.get(self.status, ()):
            raise ValueError(f"workflow cannot move from {self.status.value} to {target.value}")
        if type(reason) is not str:
            raise TypeError("workflow transition reason must be text")
        clean_reason = "".join(char if char.isprintable() else " " for char in reason[:_MAX_REASON])
        stamp = self._timestamp(at)
        entry = WorkflowTransition(self.status, target, stamp, clean_reason)
        object.__setattr__(self, "status", target)
        self.updated_at = stamp
        self._history.append(entry)

    def mark_pending(self, *, at: datetime | None = None) -> None:
        self._transition(WorkflowStatus.PENDING, at=at)

    def mark_running(self, *, at: datetime | None = None) -> None:
        if self.status is WorkflowStatus.PAUSED:
            raise ValueError("paused workflow must be resumed explicitly")
        self._transition(WorkflowStatus.RUNNING, at=at)

    def mark_completed(
        self, *, completed_task_ids: Collection[str] = (), at: datetime | None = None,
    ) -> None:
        """Require the caller's completed-task set, not proof of external cleanup."""
        planned = set(self.tasks)
        if not planned or type(completed_task_ids) not in (list, tuple, set, frozenset):
            raise ValueError("workflow completion requires a nonempty completed-task set")
        if len(completed_task_ids) != len(planned) or any(
            type(task) is not str or task not in planned for task in completed_task_ids
        ) or set(completed_task_ids) != planned:
            raise ValueError("workflow completion requires every planned task to be completed")
        self._transition(WorkflowStatus.COMPLETED, at=at)

    def mark_failed(self, reason: str = "", *, at: datetime | None = None) -> None:
        self._transition(WorkflowStatus.FAILED, at=at, reason=reason)

    def mark_paused(self, reason: str = "", *, at: datetime | None = None) -> None:
        if self.status is not WorkflowStatus.RUNNING:
            raise ValueError("only a running workflow can be paused")
        self._transition(WorkflowStatus.PAUSED, at=at, reason=reason)

    def _pause_before_start(self, *, at: datetime | None = None) -> None:
        """Preserve the CLI's explicit hold of a not-yet-started workflow."""
        if self.status not in (WorkflowStatus.DRAFT, WorkflowStatus.PENDING):
            raise ValueError("a pre-start hold requires a draft or pending workflow")
        self._transition(WorkflowStatus.PAUSED, at=at)

    def resume(self, *, at: datetime | None = None) -> None:
        if self.status is not WorkflowStatus.PAUSED:
            raise ValueError("only a paused workflow can be resumed")
        self._transition(WorkflowStatus.RUNNING, at=at)

    def mark_cancelled(self, reason: str = "", *, at: datetime | None = None) -> None:
        self._transition(WorkflowStatus.CANCELLED, at=at, reason=reason)

    def mark_governance_blocked(self, reason: str = "", *, at: datetime | None = None) -> None:
        self._transition(WorkflowStatus.GOVERNANCE_BLOCKED, at=at, reason=reason)

    def is_terminal(self) -> bool:
        """Governance blocks are terminal; the existing store allows no resume."""
        return self.status not in _TRANSITIONS
