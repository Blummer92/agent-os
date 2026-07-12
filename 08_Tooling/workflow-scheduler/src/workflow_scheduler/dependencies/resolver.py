"""Dependency resolver for workflow task execution."""

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

    def has_cycle(self) -> Tuple[bool, List[str]]:
        """Detect if dependency graph has cycles.

        Returns:
            Tuple of (has_cycle, cycle_path). If no cycle, cycle_path is empty.
        """
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        cycle_path: List[str] = []

        def visit(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            cycle_path.append(node)

            for neighbor in self.dependencies.get(node, []):
                if neighbor not in self.tasks:
                    continue
                if neighbor not in visited:
                    if visit(neighbor):
                        return True
                elif neighbor in rec_stack:
                    cycle_path.append(neighbor)
                    return True

            cycle_path.pop()
            rec_stack.remove(node)
            return False

        for task_id in self.tasks:
            if task_id not in visited:
                if visit(task_id):
                    return True, cycle_path

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
        visited: Set[str] = set()

        def traverse(tid: str) -> None:
            if tid in visited:
                return
            visited.add(tid)

            for dep in self.dependencies.get(tid, []):
                if dep in self.tasks:
                    all_deps.add(dep)
                    traverse(dep)

        traverse(task_id)
        return all_deps

    def topological_sort(self) -> Tuple[bool, List[str]]:
        """Return tasks in topological order (dependencies before dependents).

        Returns:
            Tuple of (success, sorted_task_ids). If cycle detected, success=False.
        """
        has_cycle, _ = self.has_cycle()
        if has_cycle:
            return False, []

        visited: Set[str] = set()
        sorted_list: List[str] = []

        def visit(node: str) -> None:
            if node in visited:
                return
            visited.add(node)

            for neighbor in self.dependencies.get(node, []):
                if neighbor in self.tasks:
                    visit(neighbor)

            sorted_list.append(node)

        for task_id in self.tasks:
            if task_id not in visited:
                visit(task_id)

        return True, sorted_list
