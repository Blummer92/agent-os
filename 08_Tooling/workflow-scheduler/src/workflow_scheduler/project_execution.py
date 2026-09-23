"""Dry-run project execution MVP for Agent OS Phase 2.

This module models GitHub issues as queued jobs. It is intentionally
simulation-only: no repository writes, PR creation, merges, Notion writes, or
Google Drive writes are exposed here.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple


class JobStatus(str, Enum):
    """Project execution job states for the dry-run MVP."""

    QUEUED = "queued"
    READY = "ready"
    BLOCKED = "blocked"
    RUNNING = "running"
    VALIDATION_PENDING = "validation_pending"
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_FAILED = "validation_failed"
    REVIEW_READY = "review_ready"
    COMPLETED = "completed"
    GOVERNANCE_BLOCKED = "governance_blocked"


class FixtureValidationError(ValueError):
    """Raised when a local project execution fixture is malformed."""


@dataclass
class ProjectJob:
    """A GitHub issue represented as a schedulable dry-run job."""

    id: str
    issue_number: int
    title: str
    dependencies: List[str] = field(default_factory=list)
    priority: int = 0
    status: JobStatus = JobStatus.QUEUED
    lease_owner: Optional[str] = None
    blocked_reason: Optional[str] = None
    validation_status: Optional[str] = None
    dependency_blocking_reasons: List[str] = field(default_factory=list)

    def has_active_lease(self) -> bool:
        """Return true when a worker already owns the job lease."""
        return self.lease_owner is not None


@dataclass
class ProjectExecutionEvent:
    """Audit event for the dry-run project execution cycle."""

    event_type: str
    job_id: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerLeaseState:
    """Visible dry-run lease state for worker assignment."""

    job_id: str
    worker_id: Optional[str]
    status: JobStatus
    active: bool


@dataclass
class ProjectManagerBoundary:
    """Governed boundary for the Phase 2 Project Manager role."""

    responsibilities: Tuple[str, ...] = (
        "select_ready_jobs",
        "assign_bounded_work",
        "surface_blocked_jobs",
        "preserve_governance_gates",
    )
    inputs: Tuple[str, ...] = ("job_queue", "dependency_state", "governance_state")
    outputs: Tuple[str, ...] = ("selected_jobs", "worker_assignments", "blocked_job_report")
    owned_state: Tuple[str, ...] = ("selection_history",)
    forbidden_actions: Tuple[str, ...] = (
        "merge_pull_request",
        "create_pull_request",
        "write_external_system",
        "bypass_validation_gate",
    )


class FixtureIssueQueueLoader:
    """Loads static local issue fixtures into the dry-run project model."""

    def load_jobs(self, fixture: Mapping[str, Any]) -> List[ProjectJob]:
        """Convert validated fixture data into project jobs."""
        return load_project_jobs_from_fixture_data(fixture)

    def load_execution(self, fixture: Mapping[str, Any]) -> "ProjectExecutionMVP":
        """Build a dry-run execution model from fixture data."""
        return ProjectExecutionMVP(self.load_jobs(fixture))

    def load_jobs_from_file(self, path: str | Path) -> List[ProjectJob]:
        """Load project jobs from a local JSON fixture file."""
        return load_project_jobs_from_fixture_file(path)

    def load_execution_from_file(self, path: str | Path) -> "ProjectExecutionMVP":
        """Build a dry-run execution model from a local JSON fixture file."""
        return ProjectExecutionMVP(self.load_jobs_from_file(path))

    @property
    def external_write_count(self) -> int:
        """Fixture loading performs no external writes."""
        return 0


def load_project_jobs_from_fixture_file(path: str | Path) -> List[ProjectJob]:
    """Load project jobs from a local JSON fixture path."""
    fixture_path = Path(path)
    try:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureValidationError(f"Fixture is not valid JSON: {fixture_path}") from exc
    return load_project_jobs_from_fixture_data(fixture)


def load_project_jobs_from_fixture_data(fixture: Mapping[str, Any]) -> List[ProjectJob]:
    """Validate fixture data and convert it into ProjectJob objects."""
    if not isinstance(fixture, Mapping):
        raise FixtureValidationError("Fixture must be a JSON object.")
    jobs_data = fixture.get("jobs")
    if not isinstance(jobs_data, list):
        raise FixtureValidationError("Fixture must contain a jobs list.")

    jobs: List[ProjectJob] = []
    seen_ids: set[str] = set()
    for index, raw_job in enumerate(jobs_data):
        if not isinstance(raw_job, Mapping):
            raise FixtureValidationError(f"jobs[{index}] must be an object.")
        job_id = _required_string(raw_job, "id", index)
        if job_id in seen_ids:
            raise FixtureValidationError(f"jobs[{index}].id is duplicated: {job_id}")
        seen_ids.add(job_id)
        status, blocked_reason = _fixture_status(raw_job, index)
        jobs.append(
            ProjectJob(
                id=job_id,
                issue_number=_required_int(raw_job, "issue_number", index),
                title=_required_string(raw_job, "title", index),
                dependencies=_string_list(raw_job.get("dependencies", []), index),
                priority=_optional_int(raw_job, "priority", index, default=0),
                status=status,
                blocked_reason=blocked_reason,
            )
        )
    return jobs


def _required_string(raw_job: Mapping[str, Any], key: str, index: int) -> str:
    value = raw_job.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FixtureValidationError(f"jobs[{index}].{key} must be a non-empty string.")
    return value


def _required_int(raw_job: Mapping[str, Any], key: str, index: int) -> int:
    value = raw_job.get(key)
    if type(value) is not int:
        raise FixtureValidationError(f"jobs[{index}].{key} must be an integer.")
    return value


def _optional_int(raw_job: Mapping[str, Any], key: str, index: int, default: int) -> int:
    value = raw_job.get(key, default)
    if type(value) is not int:
        raise FixtureValidationError(f"jobs[{index}].{key} must be an integer.")
    return value


def _string_list(value: Any, index: int) -> List[str]:
    if not isinstance(value, list):
        raise FixtureValidationError(f"jobs[{index}].dependencies must be a list.")
    for dep in value:
        if not isinstance(dep, str) or not dep.strip():
            raise FixtureValidationError(
                f"jobs[{index}].dependencies must contain only non-empty strings."
            )
    return list(value)


def _fixture_status(raw_job: Mapping[str, Any], index: int) -> Tuple[JobStatus, Optional[str]]:
    blocked = _optional_bool(raw_job, "blocked", index, default=False)
    governance_blocked = _optional_bool(raw_job, "governance_blocked", index, default=False)
    blocked_reason = raw_job.get("blocked_reason")
    if blocked_reason is not None and not isinstance(blocked_reason, str):
        raise FixtureValidationError(f"jobs[{index}].blocked_reason must be a string.")

    status_value = raw_job.get("status")
    if status_value is not None:
        if not isinstance(status_value, str):
            raise FixtureValidationError(f"jobs[{index}].status must be a string.")
        try:
            status = JobStatus(status_value)
        except ValueError as exc:
            raise FixtureValidationError(f"jobs[{index}].status is not supported: {status_value}") from exc
    elif governance_blocked:
        status = JobStatus.GOVERNANCE_BLOCKED
    elif blocked or blocked_reason:
        status = JobStatus.BLOCKED
    else:
        status = JobStatus.QUEUED

    if status in (JobStatus.BLOCKED, JobStatus.GOVERNANCE_BLOCKED) and not blocked_reason:
        blocked_reason = "blocked by fixture"
    return status, blocked_reason


def _optional_bool(raw_job: Mapping[str, Any], key: str, index: int, default: bool) -> bool:
    value = raw_job.get(key, default)
    if type(value) is not bool:
        raise FixtureValidationError(f"jobs[{index}].{key} must be a boolean.")
    return value


class ProjectExecutionMVP:
    """Small governed project execution model for smoke testing Phase 2."""

    def __init__(self, jobs: List[ProjectJob]):
        self.jobs: Dict[str, ProjectJob] = {job.id: job for job in jobs}
        self.audit_events: List[ProjectExecutionEvent] = []
        for job in jobs:
            self._record("job_queued", job.id, issue_number=job.issue_number)

    def _record(self, event_type: str, job_id: str, **details: Any) -> None:
        self.audit_events.append(ProjectExecutionEvent(event_type, job_id, details))

    def _job(self, job_id: str) -> ProjectJob:
        try:
            return self.jobs[job_id]
        except KeyError as exc:
            raise ValueError(f"Unknown job: {job_id}") from exc

    def _validate_worker_id(self, worker_id: str) -> None:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("Worker id must be a non-empty string.")

    def _dependencies_satisfied(self, job: ProjectJob) -> bool:
        return not self.dependency_blocking_reasons(job.id)

    def detect_dependency_cycles(self) -> List[List[str]]:
        """Detect dependency cycles using the existing resolver's DFS pattern."""
        visited: Set[str] = set()
        active: Set[str] = set()
        stack: List[str] = []
        cycles: List[List[str]] = []
        cycle_keys: Set[Tuple[str, ...]] = set()

        def visit(job_id: str) -> None:
            if job_id in active:
                start = stack.index(job_id)
                cycle = stack[start:] + [job_id]
                key = tuple(sorted(set(cycle)))
                if key not in cycle_keys:
                    cycles.append(cycle)
                    cycle_keys.add(key)
                return
            if job_id in visited:
                return
            active.add(job_id)
            stack.append(job_id)
            for dependency_id in self.jobs[job_id].dependencies:
                if dependency_id in self.jobs:
                    visit(dependency_id)
            stack.pop()
            active.remove(job_id)
            visited.add(job_id)

        for job_id in sorted(self.jobs):
            visit(job_id)
        return cycles

    def _cyclic_job_ids(self) -> Set[str]:
        cyclic: Set[str] = set()
        for cycle in self.detect_dependency_cycles():
            cyclic.update(cycle)
        return cyclic

    def _cycle_for_job(self, job_id: str) -> Optional[List[str]]:
        for cycle in self.detect_dependency_cycles():
            if job_id in cycle:
                return cycle
        return None

    def _block_cyclic_jobs(self) -> None:
        for job_id in sorted(self._cyclic_job_ids()):
            job = self._job(job_id)
            cycle = self._cycle_for_job(job_id) or [job_id]
            reason = f"dependency cycle detected: {' -> '.join(cycle)}"
            job.dependency_blocking_reasons = [reason]
            if job.status in (JobStatus.QUEUED, JobStatus.READY):
                job.status = JobStatus.BLOCKED
                job.blocked_reason = reason
                self._record("dependency_cycle_detected", job.id, cycle=cycle)

    def dependency_blocking_reasons(self, job_id: str) -> List[str]:
        """Return visible reasons a job is dependency-blocked."""
        job = self._job(job_id)
        reasons: List[str] = []
        if job_id in self._cyclic_job_ids():
            cycle = self._cycle_for_job(job_id) or [job_id]
            reasons.append(f"dependency cycle detected: {' -> '.join(cycle)}")
        for dependency_id in job.dependencies:
            dependency = self.jobs.get(dependency_id)
            if dependency is None:
                reasons.append(f"missing dependency: {dependency_id}")
            elif dependency.status != JobStatus.COMPLETED:
                reasons.append(f"waiting for dependency {dependency_id} ({dependency.status.value})")
        job.dependency_blocking_reasons = reasons
        return reasons

    def dependency_status(self) -> Dict[str, List[str]]:
        """Return dependency blocking reasons for every job."""
        return {job_id: self.dependency_blocking_reasons(job_id) for job_id in sorted(self.jobs)}

    def safe_parallel_batch(self) -> List[ProjectJob]:
        """Return all jobs safe to run together in the current dry-run state."""
        self._block_cyclic_jobs()
        ready: List[ProjectJob] = []
        for job in self.jobs.values():
            if job.status not in (JobStatus.QUEUED, JobStatus.READY):
                continue
            if job.has_active_lease():
                continue
            reasons = self.dependency_blocking_reasons(job.id)
            if reasons:
                self._record("dependency_blocked", job.id, reasons=reasons)
                continue
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.READY
                self._record("job_ready", job.id)
            ready.append(job)
        return sorted(ready, key=lambda item: (-item.priority, item.id))

    def ready_jobs(self) -> List[ProjectJob]:
        """Mark and return jobs that are ready for worker assignment."""
        return self.safe_parallel_batch()

    def lease_state(self, job_id: str) -> WorkerLeaseState:
        """Return visible worker lease state for one job."""
        job = self._job(job_id)
        return WorkerLeaseState(
            job_id=job.id,
            worker_id=job.lease_owner,
            status=job.status,
            active=job.has_active_lease(),
        )

    def worker_assignments(self) -> Dict[str, WorkerLeaseState]:
        """Return visible worker lease state for every job."""
        return {job_id: self.lease_state(job_id) for job_id in sorted(self.jobs)}

    def claim_job(self, job_id: str, worker_id: str) -> Optional[ProjectJob]:
        """Lease one ready job to a worker, preventing duplicate claims."""
        self._validate_worker_id(worker_id)
        self.ready_jobs()
        job = self._job(job_id)
        if job.status != JobStatus.READY or job.has_active_lease():
            return None
        job.lease_owner = worker_id
        job.status = JobStatus.RUNNING
        self._record("job_lease_acquired", job.id, worker_id=worker_id)
        self._record("job_claimed", job.id, worker_id=worker_id)
        return job

    def claim_next(self, worker_id: str) -> Optional[ProjectJob]:
        """Lease the highest-priority ready job to a worker."""
        self._validate_worker_id(worker_id)
        for job in self.ready_jobs():
            claimed = self.claim_job(job.id, worker_id)
            if claimed:
                return claimed
        return None

    def release_lease(self, job_id: str, worker_id: str) -> bool:
        """Release a worker-owned dry-run lease and return running jobs to ready."""
        self._validate_worker_id(worker_id)
        job = self._job(job_id)
        if job.lease_owner != worker_id:
            return False
        job.lease_owner = None
        if job.status == JobStatus.RUNNING:
            job.status = JobStatus.READY
        self._record("job_lease_released", job.id, worker_id=worker_id)
        return True

    def block_job(self, job_id: str, reason: str, governance: bool = False) -> None:
        """Block a job before assignment."""
        job = self._job(job_id)
        job.status = JobStatus.GOVERNANCE_BLOCKED if governance else JobStatus.BLOCKED
        job.blocked_reason = reason
        self._record("job_blocked", job.id, reason=reason, governance=governance)

    def record_validation(self, job_id: str, passed: bool) -> None:
        """Record simulated validation status for a leased job."""
        job = self._job(job_id)
        job.status = JobStatus.VALIDATION_PENDING
        self._record("validation_pending", job.id)
        job.validation_status = "passed" if passed else "failed"
        job.status = JobStatus.VALIDATION_PASSED if passed else JobStatus.VALIDATION_FAILED
        self._record("validation_passed" if passed else "validation_failed", job.id)

    def mark_review_ready(self, job_id: str) -> bool:
        """Move a validated job to review-ready state when allowed."""
        job = self._job(job_id)
        if job.status != JobStatus.VALIDATION_PASSED:
            return False
        job.status = JobStatus.REVIEW_READY
        self._record("review_ready", job.id)
        return True

    def mark_completed(self, job_id: str) -> None:
        """Mark a job completed for dependency-unblocking smoke tests."""
        job = self._job(job_id)
        job.status = JobStatus.COMPLETED
        job.lease_owner = None
        job.dependency_blocking_reasons = []
        self._record("job_completed", job.id)

    def transition_job(self, job_id: str, requested_status: str, actor: str) -> None:
        """Allow explicit tests for forbidden worker transitions."""
        if requested_status == "merged":
            raise ValueError("Workers cannot mark jobs merged; merge is outside this MVP.")
        job = self._job(job_id)
        try:
            job.status = JobStatus(requested_status)
        except ValueError as exc:
            raise ValueError(f"Unsupported job status: {requested_status}") from exc
        self._record("job_transitioned", job_id, actor=actor, status=requested_status)

    @property
    def external_write_count(self) -> int:
        """The dry-run MVP exposes no external write actions."""
        return 0


class ProjectManager:
    """Dry-run Project Manager that selects and assigns bounded work."""

    def __init__(self, execution: ProjectExecutionMVP, boundary: Optional[ProjectManagerBoundary] = None):
        self.execution = execution
        self.boundary = boundary or ProjectManagerBoundary()
        self.selection_history: List[str] = []

    def select_ready_jobs(self, limit: Optional[int] = None) -> List[ProjectJob]:
        """Select ready jobs without assigning workers or performing writes."""
        jobs = self.execution.safe_parallel_batch()
        selected = jobs[:limit] if limit is not None else jobs
        for job in selected:
            self.selection_history.append(job.id)
            self.execution._record("project_manager_selected", job.id)
        return selected

    def assign_next(self, worker_id: str) -> Optional[ProjectJob]:
        """Assign one ready job to a worker through the existing lease path."""
        job = self.execution.claim_next(worker_id)
        if job:
            self.execution._record("project_manager_assigned", job.id, worker_id=worker_id)
        return job

    def release_assignment(self, job_id: str, worker_id: str) -> bool:
        """Release an assigned job through the existing lease path."""
        released = self.execution.release_lease(job_id, worker_id)
        if released:
            self.execution._record("project_manager_released", job_id, worker_id=worker_id)
        return released

    def blocked_jobs(self) -> List[ProjectJob]:
        """Return jobs blocked by status or unsatisfied dependencies."""
        blocked = []
        for job in self.execution.jobs.values():
            if job.status in (JobStatus.BLOCKED, JobStatus.GOVERNANCE_BLOCKED):
                blocked.append(job)
            elif job.status == JobStatus.QUEUED and self.execution.dependency_blocking_reasons(job.id):
                blocked.append(job)
        return sorted(blocked, key=lambda item: item.id)

    def perform_forbidden_action(self, action: str) -> None:
        """Reject actions outside the Project Manager boundary."""
        if action in self.boundary.forbidden_actions:
            raise ValueError(f"Project Manager cannot perform forbidden action: {action}")
        raise ValueError(f"Unsupported Project Manager action: {action}")

    @property
    def external_write_count(self) -> int:
        """Project Manager exposes no external write actions in the dry-run MVP."""
        return 0
