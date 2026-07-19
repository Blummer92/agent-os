# ADR 0002 Details 1c: Complete `graph_digest` Payload

Companion to `adr-0002-details-01b-serialization-and-digest.md`, which
defines the serialization and hashing rule this file's payload feeds
into. This file enumerates every field so a future implementer never
has to guess "every relationship IA4D consumes."

## Source fields

Digested from every `IssueBatchNode` in the supplied `IssueBatchGraph`
(`scripts/agent_os_issue_acceptance/batch_graph.py`), plus the graph's
two dependency-pair collections:

| Field | Type | Canonical representation |
|---|---|---|
| `node_id` | `str` | verbatim |
| `readiness` | `ReadinessOutcome` | `.value` (`"ready"` / `"blocked"` / `"needs-decision"`) |
| `readiness_evidence` | `tuple[str, ...]` | sorted, deduplicated list |
| `owner` | `str \| None` | verbatim, or JSON `null` |
| `source_of_truth` | `str \| None` | verbatim, or JSON `null` |
| `affected_paths` | `tuple[str, ...]` | sorted, deduplicated list |
| `forbidden_paths` | `tuple[str, ...]` | sorted, deduplicated list |
| `dependency_ids` | `tuple[str, ...]` | sorted, deduplicated list |
| `entity_id` | `str \| None` | verbatim, or JSON `null` |
| `provenance` | `tuple[str, ...]` | sorted, deduplicated list |
| `resolved_dependencies` | `tuple[tuple[str, str], ...]` | sorted list of two-element `[from, to]` arrays |
| `unresolved_dependencies` | `tuple[tuple[str, str], ...]` | sorted list of two-element `[from, to]` arrays |

## Node ordering

Nodes are digested as a JSON array sorted ascending by `node_id`
(matching `IssueBatchGraph`'s own node identity), never by the graph's
original construction order.

## Tuple/list field ordering and deduplication

Every `tuple[str, ...]` field above (`readiness_evidence`,
`affected_paths`, `forbidden_paths`, `dependency_ids`, `provenance`) is
sorted ascending and deduplicated before hashing, exactly like
`supplied_node_ids` in `adr-0002-details-01-envelope-and-serialization.md`.
This makes the digest depend only on graph content, never on the order
values were appended during graph construction.

## Dependency-pair ordering

`resolved_dependencies` and `unresolved_dependencies` are each sorted
ascending as `(from_node_id, to_node_id)` tuples, then deduplicated.
Each pair is represented as a two-element array (`["a", "b"]`), never as
a JSON object, so pair order within the tuple is unambiguous.

## Enum, `None`, and missing-vs-empty handling

- `readiness` always serializes via `.value` — never the Python enum
  name or a raw integer.
- `None` (for `owner`, `source_of_truth`, `entity_id`) serializes as
  JSON `null`, distinct from an empty string `""`. A future
  reconstruction must not conflate "field was not supplied" with "field
  was supplied as empty."
- An empty tuple (`()`) for a list-typed field serializes as `[]`,
  distinct from the field being absent — every `IssueBatchNode` field
  is always present in the digested payload (defaults included), so
  "absent field" never occurs for a well-formed node.

## Version

0.1.0
