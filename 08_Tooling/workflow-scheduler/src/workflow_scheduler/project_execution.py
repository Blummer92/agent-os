"""Dry-run project execution MVP for Agent OS Phase 2.

This module models GitHub issues as queued jobs. It is intentionally
simulation-only: no repository writes, PR creation, merges, Notion writes, or
Google Drive writes are exposed here.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


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

    def has_active_lease(self) -> bool:
        """Return true when a worker already owns the job lease."""
        return self.lease_owner is not None


@dataclass
class ProjectExecutionEvent:
    """Audit event for the dry-run project execution cycle."""

    event_type: str
    job_id: str
    details: Dict[str, Any] = field(default_factory=dict)


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

    def _dependencies_satisfied(self, job: ProjectJob) -> bool:
        return all(self._job(dep).status == JobStatus.COMPLETED for dep in job.dependencies)

    def ready_jobs(self) -> List[ProjectJob]:
        """Mark and return jobs that are ready for worker assignment."""
        ready: List[ProjectJob] = []
        for job in self.jobs.values():
            if job.status not in (JobStatus.QUEUED, JobStatus.READY):
                continue
            if job.has_active_lease() or not self._dependencies_satisfied(job):
                continue
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.READY
                self._record("job_ready", job.id)
            ready.append(job)
        return sorted(ready, key=lambda item: (-item.priority, item.id))

    def claim_job(self, job_id: str, worker_id: str) -> Optional[ProjectJob]:
        """Lease one ready job to a worker, preventing duplicate claims."""
        self.ready_jobs()
        job = self._job(job_id)
        if job.status != JobStatus.READY or job.has_active_lease():
            return None
        job.lease_owner = worker_id
        job.status = JobStatus.RUNNING
        self._record("job_claimed", job.id, worker_id=worker_id)
        return job

    def claim_next(self, worker_id: str) -> Optional[ProjectJob]:
        """Lease the highest-priority ready job to a worker."""
        for job in self.ready_jobs():
            claimed = self.claim_job(job.id, worker_id)
            if claimed:
                return claimed
        return None

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
        jobs = self.execution.ready_jobs()
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

    def blocked_jobs(self) -> List[ProjectJob]:
        """Return jobs blocked by status or unsatisfied dependencies."""
        blocked = []
        for job in self.execution.jobs.values():
            if job.status in (JobStatus.BLOCKED, JobStatus.GOVERNANCE_BLOCKED):
                blocked.append(job)
            elif job.status == JobStatus.QUEUED and not self.execution._dependencies_satisfied(job):
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
