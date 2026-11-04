"""SQLite repository for Workflow Scheduler persistence.

Threading contract
-------------------
This repository may be shared by multiple same-process worker threads
(Phase 2E parallel task dispatch). The formal invariant:

  - Every access to the SQLite connection or any cursor object must occur
    either (a) inside a public method while self._lock is held, or
    (b) inside an internal helper method that is called only from a
    public method while self._lock is already held.
  - Public methods (create_workflow, get_workflow, update_workflow,
    create_task, get_task, update_task, list_workflow_tasks,
    create_approval_request, get_approval_request,
    update_approval_decision, log_event, get_audit_log, close) are the
    only lock-acquiring entry points -- each wraps its entire body in
    `with self._lock:`.
  - Internal helpers (_get_connection, _init_db, _migrate_tasks_table)
    assume the lock is already held by their caller and never acquire
    self._lock themselves.
  - self._lock is a threading.RLock (not a plain Lock) so a public
    method that calls an already-locked internal helper -- or, in
    update_approval_decision's case, calls another public method
    (get_approval_request) while its own lock is held -- does not
    deadlock.
  - No code path may touch self._connection or a cursor outside a
    locked context.

This guarantees safe same-process, multi-threaded sharing of one
repository instance. It does not add cross-process locking, which is
out of scope.
"""

import json
import sqlite3
import uuid
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from workflow_scheduler.models import (
    ApprovalDecision,
    ApprovalRequest,
    Task,
    TaskMode,
    TaskStatus,
    WorkflowPlan,
    WorkflowMode,
    WorkflowStatus,
)
from workflow_scheduler.time_utils import parse_utc_storage, utc_now, utc_storage_string


class SQLiteRepository:
    """SQLite-backed persistence layer for workflows, tasks, and audit events."""

    def __init__(self, db_path: str = ":memory:"):
        """Initialize repository with SQLite database."""
        self.db_path = db_path
        self._connection: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema.

        Acquires self._lock itself: construction is inherently
        single-threaded (no other thread can hold a reference to `self`
        until __init__ returns), but locking here anyway keeps the
        invariant uniformly true -- every connection/cursor access in
        this class happens under self._lock, with no exceptions to audit.
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS workflows (
                    workflow_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tasks TEXT NOT NULL,
                    dependencies TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    action TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    approval_required BOOLEAN NOT NULL,
                    depends_on TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    lease_lock TEXT,
                    production_ready BOOLEAN NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TEXT,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    paused_from_status TEXT,
                    batch_id TEXT,
                    FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
                )
                """
            )
            self._migrate_tasks_table(cursor)

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_requests (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    approver TEXT,
                    decision TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks(id)
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    task_id TEXT,
                    workflow_id TEXT,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            conn.commit()

    def _migrate_tasks_table(self, cursor: sqlite3.Cursor) -> None:
        """Add columns to a pre-existing tasks table that predate them.

        Internal helper: assumes self._lock is already held by the
        caller (_init_db). Does not acquire the lock itself.
        """
        cursor.execute("PRAGMA table_info(tasks)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        if "retry_count" not in existing_columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
        if "next_retry_at" not in existing_columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN next_retry_at TEXT")
        if "max_retries" not in existing_columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN max_retries INTEGER NOT NULL DEFAULT 3")
        if "paused_from_status" not in existing_columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN paused_from_status TEXT")
        if "batch_id" not in existing_columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN batch_id TEXT")
        if "execution_claim_token" not in existing_columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN execution_claim_token TEXT")

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create database connection.

        Internal helper: assumes self._lock is already held by the
        caller. Does not acquire the lock itself. check_same_thread=False
        is required so worker threads other than the one that created
        the connection may use it -- safety across threads is provided
        entirely by self._lock serializing all access, not by SQLite's
        own same-thread check.
        """
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def close(self) -> None:
        """Close database connection. Safe to call concurrently from
        multiple threads, and safe to call more than once."""
        with self._lock:
            if self._connection:
                self._connection.close()
                self._connection = None

    def create_workflow(self, workflow: WorkflowPlan) -> None:
        """Store workflow in database."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO workflows
                (workflow_id, title, created_by, mode, status, tasks, dependencies, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow.workflow_id,
                    workflow.title,
                    workflow.created_by,
                    workflow.mode.value,
                    workflow.status.value,
                    json.dumps(workflow.tasks),
                    json.dumps(workflow.dependencies),
                    json.dumps(workflow.metadata),
                    utc_storage_string(workflow.created_at),
                    utc_storage_string(workflow.updated_at),
                ),
            )
            conn.commit()

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowPlan]:
        """Retrieve workflow from database."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return WorkflowPlan(
                workflow_id=row["workflow_id"],
                title=row["title"],
                created_by=row["created_by"],
                mode=WorkflowMode(row["mode"]),
                status=WorkflowStatus(row["status"]),
                tasks=json.loads(row["tasks"]),
                dependencies=json.loads(row["dependencies"]),
                metadata=json.loads(row["metadata"]),
                created_at=parse_utc_storage(row["created_at"]),
                updated_at=parse_utc_storage(row["updated_at"]),
            )

    def update_workflow(self, workflow: WorkflowPlan) -> bool:
        """Update workflow in database.

        Conditional transition guard (Repair B): a terminal workflow is
        never overwritten, and a non-terminal workflow may only stay in
        place (metadata-only write) or move forward along a legitimate
        transition (draft/pending -> running/paused/cancelled,
        running -> paused/completed/failed/cancelled/governance_blocked,
        paused -> running/cancelled). A stale snapshot that would reverse
        a workflow (e.g. completed -> running, paused -> draft) is
        refused as a no-op; the return value reports whether the write
        landed. Existing callers that ignore the return value keep
        working, with the DB row unchanged on refusal.
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE workflows
                SET status = ?, tasks = ?, dependencies = ?, metadata = ?, updated_at = ?
                WHERE workflow_id = ?
                  AND status NOT IN ('completed','failed','cancelled','governance_blocked')
                  AND (
                    status = ?
                    OR (status IN ('draft','pending') AND ? IN ('running','paused','cancelled'))
                    OR (status = 'running' AND ? IN ('paused','completed','failed','cancelled','governance_blocked'))
                    OR (status = 'paused' AND ? IN ('running','cancelled'))
                  )
                """,
                (
                    workflow.status.value,
                    json.dumps(workflow.tasks),
                    json.dumps(workflow.dependencies),
                    json.dumps(workflow.metadata),
                    utc_storage_string(workflow.updated_at),
                    workflow.workflow_id,
                    workflow.status.value,
                    workflow.status.value,
                    workflow.status.value,
                    workflow.status.value,
                ),
            )
            conn.commit()
            return cursor.rowcount == 1

    def create_task(self, task: Task) -> None:
        """Store task in database."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO tasks
                (id, workflow_id, type, owner, action, idempotency_key, status, mode, priority,
                 approval_required, depends_on, payload, lease_lock, production_ready, created_at, updated_at,
                 retry_count, next_retry_at, max_retries, paused_from_status, batch_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.workflow_id,
                    task.type,
                    task.owner,
                    task.action,
                    task.idempotency_key,
                    task.status.value,
                    task.mode.value,
                    task.priority,
                    task.approval_required,
                    json.dumps(task.depends_on),
                    json.dumps(task.payload),
                    utc_storage_string(task.lease_lock) if task.lease_lock else None,
                    task.production_ready,
                    utc_storage_string(task.created_at),
                    utc_storage_string(task.updated_at),
                    task.retry_count,
                    utc_storage_string(task.next_retry_at) if task.next_retry_at else None,
                    task.max_retries,
                    task.paused_from_status,
                    task.batch_id,
                ),
            )
            conn.commit()

    def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve task from database."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return Task(
                id=row["id"],
                workflow_id=row["workflow_id"],
                type=row["type"],
                owner=row["owner"],
                action=row["action"],
                idempotency_key=row["idempotency_key"],
                status=TaskStatus(row["status"]),
                mode=TaskMode(row["mode"]),
                priority=row["priority"],
                approval_required=bool(row["approval_required"]),
                depends_on=json.loads(row["depends_on"]),
                payload=json.loads(row["payload"]),
                lease_lock=parse_utc_storage(row["lease_lock"]) if row["lease_lock"] else None,
                production_ready=bool(row["production_ready"]),
                created_at=parse_utc_storage(row["created_at"]),
                updated_at=parse_utc_storage(row["updated_at"]),
                retry_count=row["retry_count"],
                next_retry_at=parse_utc_storage(row["next_retry_at"]) if row["next_retry_at"] else None,
                max_retries=row["max_retries"],
                paused_from_status=row["paused_from_status"],
                batch_id=row["batch_id"],
            )

    def update_task(self, task: Task) -> bool:
        """Update task in database.

        Conditional transition guard (Repair B): the write is a single
        conditional UPDATE, so it holds across separate connections and
        processes, not just in-process locks. It is refused when:
        - the task currently holds an execution claim (the claim holder
          must use update_claimed_task instead);
        - the current status is terminal (completed, failed, cancelled,
          governance_blocked) — no stale writer may revive it;
        - the current status is paused and the new status is neither the
          recorded paused_from_status (a legitimate resume) nor cancelled
          (a legitimate cancel, including workflow-cascade cancel);
        - the new retry_count would move backwards (retry state may only
          stay or advance).
        All other transitions that existing code performs are preserved:
        draft/pending/approved/queued/retry_scheduled movement, approval
        pending and governance-blocked entry, pause, resume, cancel, and
        same-status field updates. Returns True when the write landed.
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE tasks
                SET status = ?, payload = ?, lease_lock = ?, updated_at = ?,
                    retry_count = ?, next_retry_at = ?, max_retries = ?, paused_from_status = ?, batch_id = ?
                WHERE id = ? AND execution_claim_token IS NULL
                  AND status NOT IN ('completed','failed','cancelled','governance_blocked')
                  AND retry_count <= ?
                  AND (status != 'paused' OR ? = paused_from_status OR ? = 'cancelled')
                """,
                (
                    task.status.value,
                    json.dumps(task.payload),
                    utc_storage_string(task.lease_lock) if task.lease_lock else None,
                    utc_storage_string(task.updated_at),
                    task.retry_count,
                    utc_storage_string(task.next_retry_at) if task.next_retry_at else None,
                    task.max_retries,
                    task.paused_from_status,
                    task.batch_id,
                    task.id,
                    task.retry_count,
                    task.status.value,
                    task.status.value,
                ),
            )
            conn.commit()
            return cursor.rowcount == 1


    def try_claim_execution(self, task_id: str) -> str | None:
        """Single-winner claim across connections and processes.

        Running tasks are not automatically stolen after a timeout.
        Recovery requires a separately proven, fenced procedure.
        """
        token = uuid.uuid4().hex
        now = utc_storage_string(utc_now())
        with self._lock:
            conn = self._get_connection()
            result = conn.execute(
                "UPDATE tasks SET status = ?, lease_lock = ?, "
                "execution_claim_token = ?, updated_at = ? "
                "WHERE id = ? AND execution_claim_token IS NULL "
                "AND lease_lock IS NULL "
                "AND status IN (?, ?, ?, ?, ?)",
                (
                    TaskStatus.RUNNING.value, now, token, now, task_id,
                    TaskStatus.DRAFT.value, TaskStatus.PENDING.value,
                    TaskStatus.APPROVED.value, TaskStatus.QUEUED.value,
                    TaskStatus.RETRY_SCHEDULED.value,
                ),
            )
            conn.commit()
            return token if result.rowcount == 1 else None

    def update_claimed_task(self, task: Task, token: str) -> bool:
        """Only the execution claim holder can persist its result.

        Repair B extension: even the holder may not write over a
        terminal status or move retry_count backwards. The holder's
        legitimate path starts from RUNNING and moves retry_count only
        forward, so this guard changes no legitimate execution outcome;
        it fails closed (False, so the executor raises) if the row was
        terminalized or its retry state advanced by another writer.
        """
        with self._lock:
            conn = self._get_connection()
            result = conn.execute(
                "UPDATE tasks SET status = ?, payload = ?, updated_at = ?, "
                "retry_count = ?, next_retry_at = ?, max_retries = ?, "
                "paused_from_status = ?, batch_id = ? "
                "WHERE id = ? AND execution_claim_token = ? "
                "AND status NOT IN ('completed','failed','cancelled','governance_blocked') "
                "AND retry_count <= ?",
                (
                    task.status.value, json.dumps(task.payload),
                    utc_storage_string(task.updated_at),
                    task.retry_count,
                    utc_storage_string(task.next_retry_at)
                    if task.next_retry_at else None,
                    task.max_retries, task.paused_from_status, task.batch_id,
                    task.id, token, task.retry_count,
                ),
            )
            conn.commit()
            return result.rowcount == 1

    def release_execution_claim(self, task_id: str, token: str) -> bool:
        """A different or superseded worker cannot release this claim."""
        with self._lock:
            conn = self._get_connection()
            result = conn.execute(
                "UPDATE tasks SET lease_lock = NULL, "
                "execution_claim_token = NULL "
                "WHERE id = ? AND execution_claim_token = ?",
                (task_id, token),
            )
            conn.commit()
            return result.rowcount == 1

    def list_workflow_tasks(self, workflow_id: str) -> List[Task]:
        """List all tasks in a workflow."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM tasks WHERE workflow_id = ? ORDER BY priority DESC", (workflow_id,))
            rows = cursor.fetchall()

            tasks = []
            for row in rows:
                tasks.append(
                    Task(
                        id=row["id"],
                        workflow_id=row["workflow_id"],
                        type=row["type"],
                        owner=row["owner"],
                        action=row["action"],
                        idempotency_key=row["idempotency_key"],
                        status=TaskStatus(row["status"]),
                        mode=TaskMode(row["mode"]),
                        priority=row["priority"],
                        approval_required=bool(row["approval_required"]),
                        depends_on=json.loads(row["depends_on"]),
                        payload=json.loads(row["payload"]),
                        lease_lock=parse_utc_storage(row["lease_lock"]) if row["lease_lock"] else None,
                        production_ready=bool(row["production_ready"]),
                        created_at=parse_utc_storage(row["created_at"]),
                        updated_at=parse_utc_storage(row["updated_at"]),
                        retry_count=row["retry_count"],
                        next_retry_at=(
                            parse_utc_storage(row["next_retry_at"]) if row["next_retry_at"] else None
                        ),
                        max_retries=row["max_retries"],
                        paused_from_status=row["paused_from_status"],
                        batch_id=row["batch_id"],
                    )
                )
            return tasks

    def create_approval_request(self, approval: ApprovalRequest) -> None:
        """Store approval request in database."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO approval_requests
                (id, task_id, requested_by, approver, decision, reason, created_at, decided_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval.id,
                    approval.task_id,
                    approval.requested_by,
                    approval.approver,
                    approval.decision.value,
                    approval.reason,
                    utc_storage_string(approval.created_at),
                    utc_storage_string(approval.decided_at) if approval.decided_at else None,
                ),
            )
            conn.commit()

    def get_approval_request(self, task_id: str) -> Optional[ApprovalRequest]:
        """Retrieve the most recent approval request for a task."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM approval_requests WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
                (task_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            return ApprovalRequest(
                id=row["id"],
                task_id=row["task_id"],
                requested_by=row["requested_by"],
                approver=row["approver"],
                decision=ApprovalDecision(row["decision"]),
                reason=row["reason"],
                created_at=parse_utc_storage(row["created_at"]),
                decided_at=parse_utc_storage(row["decided_at"]) if row["decided_at"] else None,
            )

    def update_approval_decision(
        self,
        task_id: str,
        decision: ApprovalDecision,
        approver: str,
        reason: Optional[str] = None,
    ) -> Optional[ApprovalRequest]:
        """Update the decision on a task's approval request.

        Calls the public get_approval_request() to build the return
        value while still holding self._lock. Safe only because
        self._lock is an RLock -- a plain Lock would deadlock here.
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            now = utc_storage_string(utc_now())
            cursor.execute(
                """
                UPDATE approval_requests
                SET decision = ?, approver = ?, reason = ?, decided_at = ?
                WHERE task_id = ?
                """,
                (decision.value, approver, reason, now, task_id),
            )
            conn.commit()
            return self.get_approval_request(task_id)


    def try_decide_pending_approval(
        self, task_id: str, approver: str,
        decision: ApprovalDecision, reason: Optional[str] = None,
    ) -> bool:
        """One durable winner for an existing pending task approval."""
        if decision not in (ApprovalDecision.APPROVED, ApprovalDecision.REJECTED):
            raise ValueError("Unsupported approval decision")
        with self._lock:
            conn = self._get_connection()
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT status, payload, execution_claim_token "
                    "FROM tasks WHERE id = ?", (task_id,),
                ).fetchone()
                if (
                    row is None
                    or row["status"] != TaskStatus.APPROVAL_PENDING.value
                    or row["execution_claim_token"] is not None
                ):
                    conn.rollback()
                    return False

                approval = conn.execute(
                    "SELECT id, decision FROM approval_requests "
                    "WHERE task_id = ? "
                    "ORDER BY created_at DESC, id DESC LIMIT 1",
                    (task_id,),
                ).fetchone()
                if approval and approval["decision"] != ApprovalDecision.PENDING.value:
                    conn.rollback()
                    return False

                now = utc_storage_string(utc_now())
                if approval is None:
                    approval_id = uuid.uuid4().hex
                    conn.execute(
                        "INSERT INTO approval_requests "
                        "(id, task_id, requested_by, decision, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (approval_id, task_id, approver,
                         ApprovalDecision.PENDING.value, now),
                    )
                else:
                    approval_id = approval["id"]

                update = conn.execute(
                    "UPDATE approval_requests "
                    "SET decision = ?, approver = ?, reason = ?, decided_at = ? "
                    "WHERE id = ? AND decision = ?",
                    (decision.value, approver, reason, now, approval_id,
                     ApprovalDecision.PENDING.value),
                )
                if update.rowcount != 1:
                    conn.rollback()
                    return False

                status = (
                    TaskStatus.APPROVED
                    if decision == ApprovalDecision.APPROVED
                    else TaskStatus.CANCELLED
                )
                payload = json.loads(row["payload"])
                if decision == ApprovalDecision.REJECTED and reason:
                    payload["cancellation_reason"] = reason

                update = conn.execute(
                    "UPDATE tasks SET status = ?, payload = ?, updated_at = ? "
                    "WHERE id = ? AND status = ? "
                    "AND execution_claim_token IS NULL",
                    (
                        status.value, json.dumps(payload),
                        now, task_id, TaskStatus.APPROVAL_PENDING.value,
                    ),
                )
                if update.rowcount != 1:
                    conn.rollback()
                    return False

                conn.commit()
                return True
            except BaseException:
                conn.rollback()
                raise

    def log_event(
        self,
        event_type: str,
        task_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log audit event."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            details_json = json.dumps(details or {})
            now = utc_storage_string(utc_now())

            cursor.execute(
                """
                INSERT INTO audit_log (timestamp, event_type, task_id, workflow_id, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (now, event_type, task_id, workflow_id, details_json, now),
            )
            conn.commit()

    def get_audit_log(
        self,
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve audit log events."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            if workflow_id:
                cursor.execute("SELECT * FROM audit_log WHERE workflow_id = ? ORDER BY created_at DESC", (workflow_id,))
            elif task_id:
                cursor.execute("SELECT * FROM audit_log WHERE task_id = ? ORDER BY created_at DESC", (task_id,))
            else:
                cursor.execute("SELECT * FROM audit_log ORDER BY created_at DESC")

            rows = cursor.fetchall()
            return [dict(row) for row in rows]
