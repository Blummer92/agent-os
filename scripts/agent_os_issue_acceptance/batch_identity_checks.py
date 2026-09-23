from __future__ import annotations

from .batch_extensions import GraphCheckResult
from .batch_graph import IssueBatchGraph
from .models import CheckResult, Status

CHECK_ID = "identity.entity-id-collision"
CHECK_NAME = "batch entity-id collision"


class EntityIdCollisionCheck:
    check_id = CHECK_ID

    def __call__(self, graph: IssueBatchGraph) -> GraphCheckResult:
        if not isinstance(graph, IssueBatchGraph):
            raise TypeError("graph must be an IssueBatchGraph")

        groups: dict[str, list[str]] = {}
        for node in graph.nodes:
            if node.entity_id is not None:
                groups.setdefault(node.entity_id, []).append(node.node_id)

        collisions = tuple(
            (entity_id, tuple(sorted(node_ids)))
            for entity_id, node_ids in sorted(groups.items())
            if len(node_ids) > 1
        )
        evidence = [
            f"entity_id={entity_id}; nodes={','.join(node_ids)}"
            for entity_id, node_ids in collisions
        ]
        quarantined = tuple(
            sorted(
                {
                    node_id
                    for _, node_ids in collisions
                    for node_id in node_ids
                }
            )
        )
        has_collisions = bool(collisions)
        result = CheckResult(
            name=CHECK_NAME,
            status=(
                Status.MANUAL_REVIEW if has_collisions else Status.PASS
            ),
            message=(
                "Duplicate entity_id values require identity review."
                if has_collisions
                else "No duplicate non-null entity_id values were found."
            ),
            evidence=evidence,
        )
        return GraphCheckResult(
            checks=(result,),
            quarantined_node_ids=quarantined,
            inspected_node_ids=tuple(
                sorted(node.node_id for node in graph.nodes)
            ),
            inspected_dependency_pairs=(),
        )


entity_id_collision_check = EntityIdCollisionCheck()
