# ADR 0002 Details 1b: Serialization and Digest Rules

Companion to `adr-0002-ia4d-scheduler-handoff-contract.md` and
`adr-0002-details-01-envelope-and-serialization.md`.

## Canonical serialization format (byte-exact, one rule)

The digested and transported bytes are always produced by exactly one
call shape:

```python
json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
```

Explicitly:

- **Encoding**: UTF-8.
- **`ensure_ascii=False`**: non-ASCII characters are encoded as literal
  UTF-8 bytes, not `\uXXXX` escapes, so the same logical string always
  produces the same bytes regardless of locale.
- **`sort_keys=True`**: JSON object keys are sorted lexicographically.
  This is the *only* key-ordering rule — there is no separate
  "dataclass declaration order" rule for digested/transported bytes.
  (A human-readable rendering, such as a PR comment or log line, may
  still choose to display fields in dataclass declaration order; that
  display order has no bearing on the digested/transported bytes.)
- **`separators=(",", ":")`**: compact, no extra whitespace.
- **No pretty-printing**: never `indent=...`.
- **No trailing newline**: the digest and transport payload are exactly
  the bytes `json.dumps(...)` returns; nothing is appended.
- **Representation rules**: tuples serialize as JSON arrays; enums
  serialize via their `.value` (never `.name` or a raw int); `None`
  serializes as JSON `null`; booleans serialize as JSON `true`/`false`
  (never `1`/`0` or a string); timestamps serialize as RFC 3339 UTC
  strings (never a `datetime` repr or a Unix epoch number).
- **Never** `repr()`, Python `hash()`, object identity, or dict/set
  insertion order — all of these are non-deterministic across Python
  versions, processes, or runs, and must never appear in digested or
  transported bytes.

## Deterministic collection ordering

Applied before the encoding above, so equivalent planning inputs always
serialize identically:

- `supplied_node_ids`: sorted ascending (mirrors
  `BatchPlanningResult.supplied_node_ids`, already sorted by IA4D).
- `cohort_summaries`: sorted by classification precedence, strongest
  first — `blocked` > `needs-decision` > `sequencing-review` >
  `parallel-candidate` — then by first `node_id` ascending within a tier.
  This precedence is stated directly here and in every ADR 0002 file
  that needs it; no file should point to a private implementation
  constant (such as `_ORDER` in `batch_planning.py`) as the normative
  source — that constant is an implementation detail that must match
  this ADR, not the other way around.
- `reason_codes` within a cohort: sorted ascending.

## Digest algorithm and encoding

SHA-256, lowercase hex-encoded, computed over the canonical
deterministic JSON encoding (above) of the digested substructure — never
over Python `repr()`, `hash()`, or an unordered structure.

- **`graph_digest` inputs**: the complete, exact field-by-field payload
  is enumerated in `adr-0002-details-01c-graph-digest-payload.md` —
  every `IssueBatchNode` field plus `resolved_dependencies` and
  `unresolved_dependencies`, sorted per the ordering rule above. Two
  structurally identical graphs (same nodes, same edges) always produce
  the same `graph_digest` regardless of input iteration order.
- **`planning_result_digest` inputs**: the canonical serialization of
  the full `BatchPlanningResult` (`supplied_node_ids`,
  `overall_classification`, `cohorts`, `batch_reason_codes`,
  `cycle_node_groups`), excluding the envelope's own provenance fields
  (repository, SHA, timestamp) so the digest reflects planning output
  only, not transport metadata.
- **`handoff_digest` inputs**: defined in
  `adr-0002-details-01d-handoff-digest.md` — the complete envelope
  payload excluding `handoff_digest` itself.
- Equivalent planning inputs always produce equivalent digests because
  every input is canonicalized (sorted, deterministically encoded)
  before hashing; no digest is ever computed over insertion order or
  object identity.

## Version

0.2.0

## Changelog

- 0.2.0 replaced the conflicting sort_keys/dataclass-order serialization
  rule with one byte-exact rule; replaced the `_ORDER` reference with
  direct classification precedence; pointed `graph_digest` and
  `handoff_digest` at their new dedicated field-enumeration files.
- 0.1.0 initial serialization and digest decisions.
