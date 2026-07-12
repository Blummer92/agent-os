"""SQLite repository for Workflow Scheduler persistence."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from workflow_scheduler.models import Task, TaskMode, TaskStatus, WorkflowPlan, WorkflowMode, WorkflowStatus


class SQLiteRepository:
    """SQLite-backed persistence layer for workflows, tasks, and audit events."""

    def __init__(self, db_path: str = ":memory:"):
        """Initialize repository with SQLite database."""
        self.db_path = db_path
        self._connection: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
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
                FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
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

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def close(self) -> None:
        """Close database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None

    def create_workflow(self, workflow: WorkflowPlan) -> None:
        """Store workflow in database."""
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
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO tasks
            (id, workflow_id, type, owner, action, idempotency_key, status, mode, priority,
             approval_required, depends_on, payload, lease_lock, production_ready, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        conn.commit()

    def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve task from database."""
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
        )

    def update_task(self, task: Task) -> None:
        """Update task in database."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE tasks
            SET status = ?, payload = ?, lease_lock = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                task.status.value,
                json.dumps(task.payload),
                task.lease_lock.isoformat() if task.lease_lock else None,
                task.updated_at.isoformat(),
                task.id,
            ),
        )
        conn.commit()

    def list_workflow_tasks(self, workflow_id: str) -> List[Task]:
        """List all tasks in a workflow."""
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
                )
            )
        return tasks

    def log_event(self, event_type: str, task_id: Optional[str] = None, workflow_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> None:
        """Log audit event."""
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
