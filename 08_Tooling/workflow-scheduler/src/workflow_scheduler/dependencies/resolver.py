"""Dependency resolver for workflow task execution."""

from graphlib import CycleError, TopologicalSorter
from typing import Dict, List, Set, Tuple

from workflow_scheduler.models import Task


class DependencyResolver:
    """Resolves task dependencies, detects cycles, and identifies ready tasks."""

    def __init__(self, tasks: List[Task], dependencies: Dict[str, List[str]]):
        """Initialize resolver with tasks and their dependencies.

        Args:
            tasks: List of Task objects in the workflow
            dependencies: Dict mapping task_id -> list of task_ids it depends on
        """
        self.tasks = {t.id: t for t in tasks}
        self.dependencies = dependencies

    def _known_dependency_graph(self) -> Dict[str, Tuple[str, ...]]:
        """Return the dependency graph restricted to known workflow tasks."""
        return {
            task_id: tuple(
                dependency_id
                for dependency_id in self.dependencies.get(task_id, [])
                if dependency_id in self.tasks
            )
            for task_id in self.tasks
        }

    def _has_unknown_dependencies(self) -> bool:
        """Return true when any task references a dependency outside the workflow."""
        return any(
            dependency_id not in self.tasks
            for task_id in self.tasks
            for dependency_id in self.dependencies.get(task_id, [])
        )

    def has_cycle(self) -> Tuple[bool, List[str]]:
        """Detect if dependency graph has cycles.

        Returns:
            Tuple of (has_cycle, cycle_path). If no cycle, cycle_path is empty.
        """
        sorter = TopologicalSorter(self._known_dependency_graph())
        try:
            tuple(sorter.static_order())
        except CycleError as exc:
            return True, list(exc.args[1])
        return False, []

    def get_ready_tasks(self, completed_tasks: Set[str]) -> List[str]:
        """Identify tasks ready for execution (all dependencies satisfied).

        Args:
            completed_tasks: Set of task IDs that have completed

        Returns:
            List of task IDs that can execute now
        """
        ready = []

        for task_id in self.tasks:
            if task_id in completed_tasks:
                continue

            deps = self.dependencies.get(task_id, [])
            if all(dep in completed_tasks for dep in deps):
                ready.append(task_id)

        return ready

    def get_all_dependencies(self, task_id: str) -> Set[str]:
        """Get all transitive dependencies of a task.

        Args:
            task_id: Task ID to analyze

        Returns:
            Set of all task IDs this task depends on (directly or indirectly)
        """
        all_deps: Set[str] = set()
        pending = list(reversed(self.dependencies.get(task_id, [])))

        while pending:
            dependency_id = pending.pop()
            if dependency_id not in self.tasks or dependency_id in all_deps:
                continue
            all_deps.add(dependency_id)
            pending.extend(reversed(self.dependencies.get(dependency_id, [])))

        return all_deps

    def topological_sort(self) -> Tuple[bool, List[str]]:
        """Return tasks in topological order (dependencies before dependents).

        Returns:
            Tuple of (success, sorted_task_ids). If cycle or an unknown dependency
            is detected, success=False.
        """
        if self._has_unknown_dependencies():
            return False, []

        sorter = TopologicalSorter(self._known_dependency_graph())
        try:
            return True, list(sorter.static_order())
        except CycleError:
            return False, []
