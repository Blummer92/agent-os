"""Tests for dependency resolver."""

from workflow_scheduler.dependencies import DependencyResolver
from workflow_scheduler.models import Task


def make_task(task_id: str) -> Task:
    """Build a minimal workflow task for dependency tests."""
    return Task(
        id=task_id,
        workflow_id="workflow-1",
        type="test",
        owner="system",
        action="test",
        idempotency_key=f"key-{task_id}",
    )


class TestDependencyResolver:
    """Tests for DependencyResolver."""

    def test_no_dependencies(self):
        """Test resolver with independent tasks."""
        tasks = [make_task(f"task-{i}") for i in range(3)]
        resolver = DependencyResolver(tasks, {})

        ready = resolver.get_ready_tasks(set())

        assert len(ready) == 3
        assert set(ready) == {"task-0", "task-1", "task-2"}

    def test_simple_dependency_chain(self):
        """Test simple dependency chain: 1 depends on 0."""
        tasks = [make_task("task-0"), make_task("task-1")]
        dependencies = {"task-1": ["task-0"]}
        resolver = DependencyResolver(tasks, dependencies)

        assert resolver.get_ready_tasks(set()) == ["task-0"]
        assert resolver.get_ready_tasks({"task-0"}) == ["task-1"]

    def test_multiple_dependencies(self):
        """Test task with multiple dependencies."""
        tasks = [make_task(f"task-{i}") for i in range(3)]
        dependencies = {"task-2": ["task-0", "task-1"]}
        resolver = DependencyResolver(tasks, dependencies)

        assert "task-2" not in resolver.get_ready_tasks({"task-0"})
        assert "task-2" in resolver.get_ready_tasks({"task-0", "task-1"})

    def test_cycle_detection_simple(self):
        """Test detection of simple cycle: A -> B -> A."""
        tasks = [make_task("task-A"), make_task("task-B")]
        dependencies = {"task-A": ["task-B"], "task-B": ["task-A"]}
        resolver = DependencyResolver(tasks, dependencies)

        has_cycle, cycle = resolver.has_cycle()

        assert has_cycle is True
        assert cycle == ["task-A", "task-B", "task-A"]

    def test_cycle_detection_self_loop(self):
        """Test detection of self-loop cycle."""
        resolver = DependencyResolver([make_task("task-1")], {"task-1": ["task-1"]})

        has_cycle, cycle = resolver.has_cycle()

        assert has_cycle is True
        assert cycle == ["task-1", "task-1"]

    def test_cycle_detection_excludes_non_cycle_prefix(self):
        """Cycle paths contain only the actual cycle, not the DFS prefix."""
        tasks = [make_task(task_id) for task_id in ("root", "x", "y")]
        resolver = DependencyResolver(
            tasks,
            {"root": ["x"], "x": ["y"], "y": ["x"]},
        )

        has_cycle, cycle = resolver.has_cycle()

        assert has_cycle is True
        assert cycle == ["x", "y", "x"]

    def test_cycle_detection_is_deterministic_with_multiple_cycles(self):
        """Multiple cycles expose the first cycle in task insertion order."""
        tasks = [make_task(task_id) for task_id in ("x", "y", "a", "b")]
        resolver = DependencyResolver(
            tasks,
            {
                "x": ["y"],
                "y": ["x"],
                "a": ["b"],
                "b": ["a"],
            },
        )

        first = resolver.has_cycle()
        second = resolver.has_cycle()

        assert first == (True, ["x", "y", "x"])
        assert second == first

    def test_no_cycle(self):
        """Test resolver confirms no cycle exists."""
        tasks = [make_task(f"task-{i}") for i in range(3)]
        dependencies = {"task-1": ["task-0"], "task-2": ["task-1"]}
        resolver = DependencyResolver(tasks, dependencies)

        has_cycle, _ = resolver.has_cycle()

        assert has_cycle is False

    def test_topological_sort(self):
        """Test topological sort of task dependencies."""
        tasks = [make_task(f"task-{i}") for i in range(3)]
        dependencies = {"task-1": ["task-0"], "task-2": ["task-1"]}
        resolver = DependencyResolver(tasks, dependencies)

        success, sorted_tasks = resolver.topological_sort()

        assert success is True
        assert sorted_tasks == ["task-0", "task-1", "task-2"]

    def test_topological_sort_preserves_ready_sibling_order(self):
        """Branching DAGs preserve task insertion order among ready siblings."""
        tasks = [make_task(task_id) for task_id in ("root", "right", "left", "join")]
        resolver = DependencyResolver(
            tasks,
            {
                "right": ["root"],
                "left": ["root"],
                "join": ["left", "right"],
            },
        )

        success, sorted_tasks = resolver.topological_sort()

        assert success is True
        assert sorted_tasks == ["root", "right", "left", "join"]

    def test_topological_sort_with_cycle(self):
        """Test that topological sort fails with cycle."""
        tasks = [make_task("task-A"), make_task("task-B")]
        dependencies = {"task-A": ["task-B"], "task-B": ["task-A"]}
        resolver = DependencyResolver(tasks, dependencies)

        success, sorted_tasks = resolver.topological_sort()

        assert success is False
        assert sorted_tasks == []

    def test_unknown_dependency_fails_closed_for_topological_sort(self):
        """Unknown dependencies cannot be silently treated as schedulable."""
        tasks = [make_task("a"), make_task("b")]
        resolver = DependencyResolver(tasks, {"a": ["ghost"], "b": ["a"]})

        success, sorted_tasks = resolver.topological_sort()

        assert success is False
        assert sorted_tasks == []
        assert resolver.get_ready_tasks(set()) == []

    def test_get_all_dependencies(self):
        """Test getting all transitive dependencies."""
        tasks = [make_task(f"task-{i}") for i in range(4)]
        dependencies = {
            "task-1": ["task-0"],
            "task-2": ["task-1"],
            "task-3": ["task-2"],
        }
        resolver = DependencyResolver(tasks, dependencies)

        assert resolver.get_all_dependencies("task-3") == {
            "task-0",
            "task-1",
            "task-2",
        }

    def test_deep_dependency_chain_does_not_recurse(self):
        """Cycle, ordering, and closure mechanics handle graphs beyond recursion depth."""
        count = 3000
        tasks = [make_task(f"task-{i}") for i in range(count)]
        dependencies = {
            f"task-{i}": [f"task-{i - 1}"]
            for i in range(1, count)
        }
        resolver = DependencyResolver(tasks, dependencies)

        has_cycle, cycle = resolver.has_cycle()
        success, sorted_tasks = resolver.topological_sort()
        all_dependencies = resolver.get_all_dependencies(f"task-{count - 1}")

        assert has_cycle is False
        assert cycle == []
        assert success is True
        assert sorted_tasks[0] == "task-0"
        assert sorted_tasks[-1] == f"task-{count - 1}"
        assert len(all_dependencies) == count - 1
