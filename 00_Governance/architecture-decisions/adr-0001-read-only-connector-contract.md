# ADR 0001: Read-Only Connector Contract

## Status

Accepted for M2 planning.

## Context

Agent OS has multiple Notion-facing access shapes: cached navigation index reads,
placeholder dashboard snapshots, and Workflow Scheduler read-only adapters.
M2 needs one target contract before shared-client extraction and migrations begin.

This ADR is documentation-only. It does not add a client, change runtime behavior,
write to Notion, or authorize any production system change.

## Decision

The canonical Agent OS read-only connector contract is named:

```text
ReadOnlyConnector
```

A `ReadOnlyConnector` is a governed adapter boundary for reading approved external
systems without mutating them. It has three required parts:

1. A constrained read request.
2. A read-only execution boundary.
3. A five-state contract result.

## Request Shape

Future shared clients should accept a small request object or equivalent keyword
arguments that identify:

- target system, such as Notion
- read action, such as `get_page`, `get_database`, or `query_database`
- target identifier, such as page id, database id, block id, or registry key
- optional read filter, cursor, page size, and tracing metadata
- source context sufficient to report whether the data is cached or live

The request must not carry write actions, source-of-truth changes, approval
decisions, readiness updates, sharing updates, or governed-field edits.

## Execution Boundary

Read-only connectors may use only operations that retrieve data. For Notion, this
allows GET endpoints and the Notion database query endpoint when it is restricted
to row retrieval and cannot create, update, archive, comment, invite, or delete.

Connector code must centralize any allowed HTTP verbs/endpoints so tests can
prove no write endpoint is exposed.

## Result Shape

`ReadOnlyConnector` results should use the existing Scheduler five-state result
shape:

```text
status: success | failure | retryable | blocked | approval-required
message: human-readable summary
output: optional read payload
metadata: optional tracing and source-context metadata
error: optional structured error
```

`retryable` results must include `retry_after`. `blocked` results must include a
blocked reason. `approval-required` results must include an approval reason.

## Rejected Alternatives

### Keep Each Notion Access Path Independent

Rejected. Divergent adapters make it unclear which behavior is canonical and
force future migrations to reconcile the same boundary repeatedly.

### Treat The Workflow Scheduler TaskAdapter As The Only Contract

Rejected as too narrow. Scheduler adapters remain important consumers, but the
shared read-only client must also support navigation lookups and dashboard
snapshot tooling without making Scheduler task state the universal input model.

### Require GET-Only For Every Read Connector

Rejected as overbroad. Some APIs use read-semantic POST endpoints for queries.
Those endpoints are allowed only when explicitly hardcoded, narrow, and tested as
non-mutating.

## Compatibility Approach

Existing call sites may keep their local interfaces during migration if they wrap
or adapt to `ReadOnlyConnector` at the boundary. Compatibility shims must be
read-only and must not add new write capability.

## Migration Notes

- B2 should extract the shared Notion read-only client around this contract.
- B3 should adapt `dashboard-migration-verification/snapshot_notion.py` through
  the shared client while preserving current placeholder behavior.
- B4 should align Scheduler `notion_readonly_adapter.py` with this contract or
  document it as the reference implementation for the Notion transport layer.
- B5 should shim or deprecate the root offline Notion skeleton so it no longer
  appears to be an independent connector contract.

## Validation Expectations

- Contract docs remain under the Markdown line limit.
- No runtime behavior changes are introduced by this ADR.
- Future implementation PRs must include tests proving read-only boundaries.

## Version

0.1.0

## Changelog

- 0.1.0 accepted `ReadOnlyConnector` as the M2 canonical read-only connector
  contract for B1.
