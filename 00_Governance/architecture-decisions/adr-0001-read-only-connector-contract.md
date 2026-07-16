# ADR 0001: Read-Only Connector Contract

## Status

Accepted for M2 planning.

## Supersession Note

This ADR is superseded for canonical naming by
`01_Shared_Standards/navigation/connector-contract-adr.md`.

The canonical Agent OS read-only connector contract name is
**Navigation Registry Read Contract**.

The term `ReadOnlyConnector` may remain as implementation or compatibility
terminology for adapter classes, result boundaries, tests, or legacy references,
but it is not the canonical governance name for M2 connector planning.

Future B2, B3, B4, and B5 documentation should reference the Navigation Registry
Read Contract as the canonical contract and should use `ReadOnlyConnector` only
when referring to concrete code, compatibility shims, or legacy adapter naming.

## Context

Agent OS has multiple Notion-facing access shapes: cached navigation index reads,
placeholder dashboard snapshots, and Workflow Scheduler read-only adapters. M2
needs one target contract before shared-client extraction and migrations begin.
This ADR is documentation-only. It does not add a client, change runtime
behavior, write to Notion, or authorize production system changes.

## Decision

The canonical Agent OS read-only connector contract is named `ReadOnlyConnector`.
It is a governed adapter boundary for reading approved external systems without
mutating them. It has three required parts: constrained read request, read-only
execution boundary, and five-state contract result.

## Request Shape

Future shared clients should accept a request object, or equivalent keyword
arguments, that identifies:

- target system, such as Notion
- read action, such as `get_page`, `get_database`, or `query_database`
- target identifier, such as page id, database id, block id, or registry key
- optional read filter, cursor, page size, and tracing metadata
- whether the data is cached or live

The request must not carry write actions, source-of-truth changes, approval
decisions, readiness updates, sharing updates, or governed-field edits.

## Execution Boundary

Read-only connectors may use only operations that retrieve data. For Notion,
this allows GET endpoints and the database query endpoint when it is restricted
to row retrieval and cannot create, update, archive, comment, invite, or delete.
Connector code must centralize allowed verbs/endpoints so tests can prove no
write endpoint is exposed.

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

`retryable` results must include `retry_after`; `blocked` must include a blocked
reason; `approval-required` must include an approval reason.

## Rejected Alternatives

- Independent Notion access paths: rejected because divergent adapters make the
  canonical behavior unclear.
- Scheduler `TaskAdapter` as the only contract: rejected because the shared
  client must also support navigation lookups and dashboard snapshot tools.
- Universal GET-only rule: rejected because some APIs use read-semantic POST
  query endpoints; these are allowed only when hardcoded and tested read-only.

## Compatibility And Migration

Existing call sites may keep local interfaces during migration if they wrap or
adapt to `ReadOnlyConnector` at the boundary. Compatibility shims must remain
read-only and must not add new write capability.

- B2 extracts the shared Notion read-only client around this contract.
- B3 adapts `dashboard-migration-verification/snapshot_notion.py` through it.
- B4 aligns Scheduler `notion_readonly_adapter.py` with it or documents that
  adapter as the Notion transport reference.
- B5 shims or deprecates the root offline Notion skeleton.

## Validation Expectations

- This ADR remains under the Markdown line limit.
- No runtime behavior changes are introduced by this ADR.
- Future implementation PRs include tests proving read-only boundaries.

## Version

0.1.0

## Changelog

- 0.1.0 accepted `ReadOnlyConnector` as the M2 canonical read-only connector
  contract for B1.
