"""Dry-run project execution MVP for Agent OS Phase 2.

This module models GitHub issues as queued jobs. It is intentionally
simulation-only: no repository writes, PR creation, merges, Notion writes, or
Google Drive writes are exposed here.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple


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
