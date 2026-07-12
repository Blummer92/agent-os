"""Tests for dependency resolver."""

import pytest

from workflow_scheduler.dependencies import DependencyResolver
from workflow_scheduler.models import Task


class TestDependencyResolver:
    """Tests for DependencyResolver."""

    def test_no_dependencies(self):
        """Test resolver with independent tasks."""
        tasks = [
            Task(
                id=f"task-{i}",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key=f"key-{i}",
            )
            for i in range(3)
        ]

        resolver = DependencyResolver(tasks, {})
        ready = resolver.get_ready_tasks(set())

        assert len(ready) == 3
        assert set(ready) == {"task-0", "task-1", "task-2"}

    def test_simple_dependency_chain(self):
        """Test simple dependency chain: 1 depends on 0."""
        tasks = [
            Task(
                id="task-0",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key="key-0",
            ),
            Task(
                id="task-1",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key="key-1",
            ),
        ]

        dependencies = {"task-1": ["task-0"]}
        resolver = DependencyResolver(tasks, dependencies)

        # Initially, only task-0 is ready
        ready = resolver.get_ready_tasks(set())
        assert ready == ["task-0"]

        # After task-0 completes, task-1 is ready
        ready = resolver.get_ready_tasks({"task-0"})
        assert ready == ["task-1"]

    def test_multiple_dependencies(self):
        """Test task with multiple dependencies."""
        tasks = [
            Task(
                id=f"task-{i}",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key=f"key-{i}",
            )
            for i in range(3)
        ]

        dependencies = {"task-2": ["task-0", "task-1"]}
        resolver = DependencyResolver(tasks, dependencies)

        # task-2 not ready when only task-0 complete
        ready = resolver.get_ready_tasks({"task-0"})
        assert "task-2" not in ready

        # task-2 ready when both dependencies complete
        ready = resolver.get_ready_tasks({"task-0", "task-1"})
        assert "task-2" in ready

    def test_cycle_detection_simple(self):
        """Test detection of simple cycle: A -> B -> A."""
        tasks = [
            Task(
                id="task-A",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key="key-A",
            ),
            Task(
                id="task-B",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key="key-B",
            ),
        ]

        dependencies = {"task-A": ["task-B"], "task-B": ["task-A"]}
        resolver = DependencyResolver(tasks, dependencies)

        has_cycle, cycle = resolver.has_cycle()
        assert has_cycle is True
        assert len(cycle) > 0

    def test_cycle_detection_self_loop(self):
        """Test detection of self-loop cycle."""
        tasks = [
            Task(
                id="task-1",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key="key-1",
            ),
        ]

        dependencies = {"task-1": ["task-1"]}
        resolver = DependencyResolver(tasks, dependencies)

        has_cycle, cycle = resolver.has_cycle()
        assert has_cycle is True

    def test_no_cycle(self):
        """Test resolver confirms no cycle exists."""
        tasks = [
            Task(
                id=f"task-{i}",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key=f"key-{i}",
            )
            for i in range(3)
        ]

        dependencies = {"task-1": ["task-0"], "task-2": ["task-1"]}
        resolver = DependencyResolver(tasks, dependencies)

        has_cycle, _ = resolver.has_cycle()
        assert has_cycle is False

    def test_topological_sort(self):
        """Test topological sort of task dependencies."""
        tasks = [
            Task(
                id=f"task-{i}",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key=f"key-{i}",
            )
            for i in range(3)
        ]

        dependencies = {"task-1": ["task-0"], "task-2": ["task-1"]}
        resolver = DependencyResolver(tasks, dependencies)

        success, sorted_tasks = resolver.topological_sort()
        assert success is True
        assert len(sorted_tasks) == 3

        # Check ordering: task-0 before task-1, task-1 before task-2
        task_0_idx = sorted_tasks.index("task-0")
        task_1_idx = sorted_tasks.index("task-1")
        task_2_idx = sorted_tasks.index("task-2")

        assert task_0_idx < task_1_idx < task_2_idx

    def test_topological_sort_with_cycle(self):
        """Test that topological sort fails with cycle."""
        tasks = [
            Task(
                id="task-A",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key="key-A",
            ),
            Task(
                id="task-B",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key="key-B",
            ),
        ]

        dependencies = {"task-A": ["task-B"], "task-B": ["task-A"]}
        resolver = DependencyResolver(tasks, dependencies)

        success, sorted_tasks = resolver.topological_sort()
        assert success is False
        assert len(sorted_tasks) == 0

    def test_get_all_dependencies(self):
        """Test getting all transitive dependencies."""
        tasks = [
            Task(
                id=f"task-{i}",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key=f"key-{i}",
            )
            for i in range(4)
        ]

        dependencies = {
            "task-1": ["task-0"],
            "task-2": ["task-1"],
            "task-3": ["task-2"],
        }
        resolver = DependencyResolver(tasks, dependencies)

        # task-3 transitively depends on task-0, task-1, task-2
        all_deps = resolver.get_all_dependencies("task-3")
        assert all_deps == {"task-0", "task-1", "task-2"}
