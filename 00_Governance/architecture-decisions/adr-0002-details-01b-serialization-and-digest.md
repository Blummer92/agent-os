# ADR 0002 Details 1b: Serialization and Digest Rules

Companion to `adr-0002-ia4d-scheduler-handoff-contract.md` and
`adr-0002-details-01-envelope-and-serialization.md`.

## Canonical serialization format

Deterministic JSON (`json.dumps(..., sort_keys=True, separators=(",", ":"))`),
matching the existing repository-wide pattern in
`08_Tooling/reusable-capability-registry/src/reusable_capability_registry/serialization.py`.
No YAML, pickle, or binary format, so the artifact stays diffable and
dependency-free.

## Deterministic field ordering

Two rules, applied consistently everywhere ordering matters:

- **Struct field order** in the JSON object mirrors the dataclass
  declaration order in details-01 (stable, not alphabetical), so a diff
  between two handoffs is a field-by-field diff.
- **Collection ordering**: `supplied_node_ids` is sorted ascending
  (mirrors `BatchPlanningResult.supplied_node_ids`, already sorted by
  IA4D). `cohort_summaries` is sorted by `(classification rank per
  `_ORDER` in `batch_planning.py`, then first `node_id`)`.
  `reason_codes` within a cohort are sorted ascending. This guarantees
  equivalent planning inputs always serialize identically.

## Digest algorithm and encoding

SHA-256, lowercase hex-encoded, computed over the canonical
deterministic JSON encoding (above) of the digested substructure — never
over Python `repr()`, `hash()`, or an unordered structure.

- **`graph_digest` inputs**: the canonical serialization of the supplied
  `IssueBatchGraph` — every node id, every declared dependency edge, and
  every declared forbidden/required relationship IA4D consumes — sorted
  per the ordering rule above. Two structurally identical graphs (same
  nodes, same edges) always produce the same `graph_digest` regardless
  of input iteration order.
- **`planning_result_digest` inputs**: the canonical serialization of
  the full `BatchPlanningResult` (`supplied_node_ids`,
  `overall_classification`, `cohorts`, `batch_reason_codes`,
  `cycle_node_groups`), excluding the envelope's own provenance fields
  (repository, SHA, timestamp) so the digest reflects planning output
  only, not transport metadata.
- Equivalent planning inputs always produce equivalent digests because
  both inputs are canonicalized (sorted, deterministically encoded)
  before hashing; no digest is ever computed over insertion order or
  object identity.

## Version

0.1.0
