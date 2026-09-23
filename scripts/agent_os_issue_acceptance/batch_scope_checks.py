from __future__ import annotations

from .batch_extensions import GraphCheckResult, GraphCheckRun
from .batch_graph import IssueBatchGraph
from .models import CheckResult, Status

UNRESOLVED_CHECK_ID = "relationships.unresolved-dependencies"
UNRESOLVED_CHECK_NAME = "batch unresolved dependencies"
COVERAGE_CHECK_NAME = "batch input-scope coverage"
COVERAGE_SCOPE = "coverage_scope=supplied-graph-only"


class UnresolvedDependencyCheck:
    check_id = UNRESOLVED_CHECK_ID

    def __call__(self, graph: IssueBatchGraph) -> GraphCheckResult:
        if not isinstance(graph, IssueBatchGraph):
            raise TypeError("graph must be an IssueBatchGraph")

        pairs = tuple(sorted(set(graph.unresolved_dependencies)))
        has_unresolved = bool(pairs)
        result = CheckResult(
            name=UNRESOLVED_CHECK_NAME,
            status=Status.MANUAL_REVIEW if has_unresolved else Status.PASS,
            message=(
                "Unresolved dependency pairs require review."
                if has_unresolved
                else "No unresolved dependency pairs were supplied."
            ),
            evidence=[
                f"source={source}; target={target}"
                for source, target in pairs
            ],
        )
        return GraphCheckResult(
            checks=(result,),
            inspected_node_ids=tuple(
                sorted(node.node_id for node in graph.nodes)
            ),
            inspected_dependency_pairs=pairs,
        )


unresolved_dependency_check = UnresolvedDependencyCheck()


def evaluate_input_scope_coverage(
    graph: IssueBatchGraph,
    run: GraphCheckRun,
) -> CheckResult:
    if not isinstance(graph, IssueBatchGraph):
        raise TypeError("graph must be an IssueBatchGraph")
    if not isinstance(run, GraphCheckRun):
        raise TypeError("run must be a GraphCheckRun")

    supplied_nodes = {node.node_id for node in graph.nodes}
    supplied_resolved = set(graph.resolved_dependencies)
    supplied_unresolved = set(graph.unresolved_dependencies)
    inspected_nodes = set(run.inspected_node_ids)
    inspected_pairs = set(run.inspected_dependency_pairs)

    findings = {
        *(f"missing_node={node_id}" for node_id in supplied_nodes - inspected_nodes),
        *(
            f"missing_resolved_pair={source},{target}"
            for source, target in supplied_resolved - inspected_pairs
        ),
        *(
            f"missing_unresolved_pair={source},{target}"
            for source, target in supplied_unresolved - inspected_pairs
        ),
        *(f"failed_check_id={check_id}" for check_id in run.failed_check_ids),
    }
    evidence = [COVERAGE_SCOPE, *sorted(findings)]
    covered = not findings
    return CheckResult(
        name=COVERAGE_CHECK_NAME,
        status=Status.PASS if covered else Status.MANUAL_REVIEW,
        message=(
            "input_scope_covered"
            if covered
            else "Supplied graph input coverage requires review."
        ),
        evidence=evidence,
    )
