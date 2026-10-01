"""Human-readable scheduler status wrapper (PYLIB5 pilot, #3222).

Thin Typer + Rich operator command. It calls the existing model/query layer
(``SQLiteRepository``, the models, and the batch-rollup rules in
``workflow_scheduler.cli``) and renders a human summary. The machine path is
plain ``json.dumps`` and never passes through Rich. Presentation output is
never authority or source-of-truth state: the repository remains canonical.

Exit codes: ``0`` status rendered · ``1`` workflow not found or database
unreachable · ``2`` usage error (Typer).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
from collections import Counter
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from workflow_scheduler.cli import _compute_batch_rollup
from workflow_scheduler.models import Task
from workflow_scheduler.repository import SQLiteRepository

_UNBATCHED = "unbatched"

_ROLLUP_STYLES = {
    "completed": "green",
    "failed": "red",
    "partial": "yellow",
    "not_started": "dim",
}


class OutputFormat(str, Enum):
    """Output format. Type-driven: Typer validates and renders help from this."""

    text = "text"
    json = "json"


app = typer.Typer(
    name="agent-os-scheduler-status",
    help=(
        "Human-readable Workflow Scheduler status (PYLIB5 pilot). "
        "Read-only: never creates, updates, or executes work."
    ),
    add_completion=False,
)


class _ReadOnlySQLiteRepository(SQLiteRepository):
    """Reuse canonical queries without initialization or schema migration."""

    def __init__(self, db: Path):
        self.db_path = db.resolve().as_uri() + "?mode=ro"
        self._connection = None
        self._lock = threading.RLock()

    def _get_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(
                self.db_path, uri=True, check_same_thread=False
            )
            self._connection.row_factory = sqlite3.Row
        return self._connection


def build_status_payload(
    workflow_id: str, repo: SQLiteRepository
) -> Optional[Dict[str, Any]]:
    """Pure query over the existing repository layer.

    Returns a JSON-safe dict, or None when the workflow does not exist.
    """
    workflow = repo.get_workflow(workflow_id)
    if workflow is None:
        return None
    tasks: List[Task] = repo.list_workflow_tasks(workflow_id)
    batches: Dict[str, List[Task]] = {}
    for task in tasks:
        batches.setdefault(task.batch_id or _UNBATCHED, []).append(task)
    batch_rows = []
    for batch_id in sorted(batches):
        batch_tasks = batches[batch_id]
        counts = Counter(t.status.value for t in batch_tasks)
        batch_rows.append(
            {
                "batch_id": batch_id,
                "rollup": _compute_batch_rollup([t.status for t in batch_tasks]),
                "task_count": len(batch_tasks),
                "status_counts": {s: counts[s] for s in sorted(counts)},
                "tasks": sorted(t.id for t in batch_tasks),
            }
        )
    return {
        "workflow_id": workflow.workflow_id,
        "title": workflow.title,
        "status": workflow.status.value,
        "mode": workflow.mode.value,
        "task_count": len(tasks),
        "batches": batch_rows,
    }


def render_text(payload: Dict[str, Any]) -> None:
    """Human rendering via Rich. Never used for the machine path."""
    # Default Console honors non-TTY and NO_COLOR automatically.
    console = Console(force_terminal=sys.stdout.isatty())
    console.print(
        f"[bold]Workflow[/bold] {payload['workflow_id']} — {payload['title']}"
    )
    console.print(
        f"Status: {payload['status']}   "
        f"Mode: {payload['mode']}   "
        f"Tasks: {payload['task_count']}"
    )
    table = Table(title="Batches")
    table.add_column("Batch")
    table.add_column("Rollup")
    table.add_column("Tasks", justify="right")
    table.add_column("Status counts")
    for batch in payload["batches"]:
        counts = ", ".join(
            f"{name}={n}" for name, n in batch["status_counts"].items()
        )
        rollup = Text(
            batch["rollup"], style=_ROLLUP_STYLES.get(batch["rollup"], "")
        )
        table.add_row(batch["batch_id"], rollup, str(batch["task_count"]), counts)
    console.print(table)


def render_json(payload: Dict[str, Any]) -> None:
    """Machine path: plain json.dumps, never Rich."""
    print(json.dumps(payload, indent=2, sort_keys=True))


@app.command()
def status(
    workflow_id: str = typer.Argument(..., help="Workflow ID to inspect."),
    db: Path = typer.Option(
        Path("workflow_scheduler.db"),
        "--db",
        help="Scheduler SQLite database path.",
    ),
    output_format: OutputFormat = typer.Option(
        OutputFormat.text,
        "--format",
        help="Output format: human-readable text or machine JSON.",
    ),
) -> None:
    """Show a human-readable status summary for one scheduler workflow."""
    if not db.exists():
        print(f"error: database not found: {db}", file=sys.stderr)
        raise typer.Exit(1)
    try:
        repo = _ReadOnlySQLiteRepository(db)
        try:
            payload = build_status_payload(workflow_id, repo)
        finally:
            repo.close()
    except (sqlite3.Error, OSError) as exc:
        print(f"error: cannot read database {db}: {exc}", file=sys.stderr)
        raise typer.Exit(1)
    if payload is None:
        print(f"error: workflow not found: {workflow_id}", file=sys.stderr)
        raise typer.Exit(1)
    if output_format is OutputFormat.json:
        render_json(payload)
    else:
        render_text(payload)


def main() -> None:
    # Explicit program name: never expose the module filename.
    app(prog_name="agent-os-scheduler-status")


if __name__ == "__main__":
    main()
