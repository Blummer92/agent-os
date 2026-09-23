"""Tests for job queue."""

import pytest

from workflow_scheduler.models import Task, TaskStatus
from workflow_scheduler.queue import JobQueue


class TestJobQueue:
    """Tests for JobQueue."""

    def test_enqueue_and_dequeue(self):
        """Test enqueueing and dequeueing tasks."""
        queue = JobQueue()
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        queue.enqueue(task)
        assert queue.size() == 1

        dequeued = queue.dequeue()
        assert dequeued.id == "task-1"
        assert queue.size() == 0

    def test_priority_ordering(self):
        """Test that tasks are ordered by priority (higher first)."""
        queue = JobQueue()

        for i in range(3):
            task = Task(
                id=f"task-{i}",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key=f"key-{i}",
                priority=i,
            )
            queue.enqueue(task)

        # Should dequeue in priority order: 2, 1, 0
        assert queue.dequeue().id == "task-2"
        assert queue.dequeue().id == "task-1"
        assert queue.dequeue().id == "task-0"

    def test_peek(self):
        """Test peeking at next task without removing it."""
        queue = JobQueue()
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        queue.enqueue(task)
        peeked = queue.peek()

        assert peeked.id == "task-1"
        assert queue.size() == 1  # Not removed

    def test_remove_by_id(self):
        """Test removing task by ID."""
        queue = JobQueue()

        for i in range(3):
            task = Task(
                id=f"task-{i}",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key=f"key-{i}",
            )
            queue.enqueue(task)

        removed = queue.remove("task-1")
        assert removed is True
        assert queue.size() == 2

        removed = queue.remove("nonexistent")
        assert removed is False

    def test_is_empty(self):
        """Test checking if queue is empty."""
        queue = JobQueue()
        assert queue.is_empty()

        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )
        queue.enqueue(task)
        assert not queue.is_empty()

    def test_dequeue_empty_queue(self):
        """Test dequeueing from empty queue."""
        queue = JobQueue()
        result = queue.dequeue()
        assert result is None

    def test_peek_empty_queue(self):
        """Test peeking at empty queue."""
        queue = JobQueue()
        result = queue.peek()
        assert result is None

    def test_list_queued(self):
        """Test listing all queued tasks."""
        queue = JobQueue()

        for i in range(3):
            task = Task(
                id=f"task-{i}",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key=f"key-{i}",
            )
            queue.enqueue(task)

        tasks = queue.list_queued()
        assert len(tasks) == 3
        assert tasks[0].id == "task-0"  # All same priority
