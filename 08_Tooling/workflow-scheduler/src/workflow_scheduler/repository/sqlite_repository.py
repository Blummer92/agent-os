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
import threading
from datetime import datetime
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

            # Workflows table
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

            # Tasks table
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

            # Approval requests table
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

            # Audit log table
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
        """Add columns to a pre-existing tasks table that predate them
        (Phase 2B retry columns, Phase 2C paused_from_status, Phase 2D
        batch_id). CREATE TABLE IF NOT EXISTS only applies new columns to
        brand-new databases; existing local DBs need this explicit
        migration.

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
                    workflow.created_at.isoformat(),
                    workflow.updated_at.isoformat(),
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
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

    def update_workflow(self, workflow: WorkflowPlan) -> None:
        """Update workflow in database."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE workflows
                SET status = ?, tasks = ?, dependencies = ?, metadata = ?, updated_at = ?
                WHERE workflow_id = ?
                """,
                (
                    workflow.status.value,
                    json.dumps(workflow.tasks),
                    json.dumps(workflow.dependencies),
                    json.dumps(workflow.metadata),
                    workflow.updated_at.isoformat(),
                    workflow.workflow_id,
                ),
            )
            conn.commit()

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
                    task.lease_lock.isoformat() if task.lease_lock else None,
                    task.production_ready,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                    task.retry_count,
                    task.next_retry_at.isoformat() if task.next_retry_at else None,
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
                lease_lock=datetime.fromisoformat(row["lease_lock"]) if row["lease_lock"] else None,
                production_ready=bool(row["production_ready"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                retry_count=row["retry_count"],
                next_retry_at=datetime.fromisoformat(row["next_retry_at"]) if row["next_retry_at"] else None,
                max_retries=row["max_retries"],
                paused_from_status=row["paused_from_status"],
                batch_id=row["batch_id"],
            )

    def update_task(self, task: Task) -> None:
        """Update task in database."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE tasks
                SET status = ?, payload = ?, lease_lock = ?, updated_at = ?,
                    retry_count = ?, next_retry_at = ?, max_retries = ?, paused_from_status = ?, batch_id = ?
                WHERE id = ?
                """,
                (
                    task.status.value,
                    json.dumps(task.payload),
                    task.lease_lock.isoformat() if task.lease_lock else None,
                    task.updated_at.isoformat(),
                    task.retry_count,
                    task.next_retry_at.isoformat() if task.next_retry_at else None,
                    task.max_retries,
                    task.paused_from_status,
                    task.batch_id,
                    task.id,
                ),
            )
            conn.commit()

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
                        lease_lock=datetime.fromisoformat(row["lease_lock"]) if row["lease_lock"] else None,
                        production_ready=bool(row["production_ready"]),
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"]),
                        retry_count=row["retry_count"],
                        next_retry_at=datetime.fromisoformat(row["next_retry_at"]) if row["next_retry_at"] else None,
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
                    approval.created_at.isoformat(),
                    approval.decided_at.isoformat() if approval.decided_at else None,
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
                created_at=datetime.fromisoformat(row["created_at"]),
                decided_at=datetime.fromisoformat(row["decided_at"]) if row["decided_at"] else None,
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

            now = datetime.utcnow().isoformat()
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

    def log_event(self, event_type: str, task_id: Optional[str] = None, workflow_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> None:
        """Log audit event."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            details_json = json.dumps(details or {})
            now = datetime.utcnow().isoformat()

            cursor.execute(
                """
                INSERT INTO audit_log (timestamp, event_type, task_id, workflow_id, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (now, event_type, task_id, workflow_id, details_json, now),
            )
            conn.commit()

    def get_audit_log(self, workflow_id: Optional[str] = None, task_id: Optional[str] = None) -> List[Dict[str, Any]]:
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
