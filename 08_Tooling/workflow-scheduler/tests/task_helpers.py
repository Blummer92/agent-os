"""Plain task builders shared by workflow-scheduler tests.

Keep these helpers as ordinary imported functions so pytest collection, fixture
scope, object lifetime, and generated node IDs remain unchanged.
"""

from workflow_scheduler.models import Task


def make_plain_task(task_id: str = "task-1", **overrides) -> Task:
    """Build the common non-governed task used by lifecycle-style tests."""
    defaults = dict(
        id=task_id,
        workflow_id="workflow-1",
        type="test",
        owner="system",
        action="test_action",
        idempotency_key=f"key-{task_id}",
    )
    defaults.update(overrides)
    return Task(**defaults)
