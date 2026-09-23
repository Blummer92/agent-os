"""Priority-based job queue for task execution."""

from typing import List, Optional

from workflow_scheduler.models import Task, TaskStatus


class JobQueue:
    """FIFO queue with priority ordering for task execution."""

    def __init__(self):
        """Initialize empty queue."""
        self._queue: List[Task] = []

    def enqueue(self, task: Task) -> None:
        """Add task to queue, maintaining priority order (higher priority first)."""
        self._queue.append(task)
        self._queue.sort(key=lambda t: (-t.priority, t.created_at))

    def dequeue(self) -> Optional[Task]:
        """Remove and return highest-priority task from queue."""
        if self._queue:
            return self._queue.pop(0)
        return None

    def peek(self) -> Optional[Task]:
        """Return highest-priority task without removing it."""
        if self._queue:
            return self._queue[0]
        return None

    def remove(self, task_id: str) -> bool:
        """Remove task by ID from queue."""
        for i, task in enumerate(self._queue):
            if task.id == task_id:
                self._queue.pop(i)
                return True
        return False

    def size(self) -> int:
        """Return current queue size."""
        return len(self._queue)

    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return len(self._queue) == 0

    def list_queued(self) -> List[Task]:
        """Return all queued tasks in priority order."""
        return list(self._queue)
