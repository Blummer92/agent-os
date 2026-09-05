# Visual Asset Sync — Reconciliation Planner

Deterministic reconciliation tooling for reviewed visual assets. The planner core
performs zero network calls and zero external writes. Optional Sheets and Notion
adapters perform only separately authorized bounded reads.

Issue #739 adds an **offline, authorization-gated mutation boundary** without
activating any live write. `mutation_adapter.py` converts only planner-approved
`UPDATE_EXISTING` and `CREATE_MISSING` entries into deterministic actions. Dry-run
is the default and makes zero client calls. Non-dry execution requires an exact,
immutable `MutationAuthorization` and an injected client supplied by a separately
authorized runtime.

Adapter contracts:

- [`SHEETS_ADAPTER.md`](SHEETS_ADAPTER.md) — fixture-first Google Sheets values
  extraction for Issue #731.
- [`NOTION_ADAPTER.md`](NOTION_ADAPTER.md) — fixture-first read-only Notion
  extraction for Issue #735.
- `mutation_adapter.py` — #739 mutation planning/execution boundary; no concrete
  credential or network client is included.
- `orchestration.py` — #739 disabled-by-default one-run wrapper.

## Mutation authorization

Live-capable calls fail closed unless authorization binds the exact Notion data
source, pinned `Notion-Version`, planner digest, approved action classes,
property allowlist, credential-injection route, update/create/total ceilings,
validity window, and explicit dry-run/live mode. Authorization never grants
schema, sharing, relation, comment, file, archive, delete, Sheets, or Drive
mutation authority.

Action evidence keys and plan digests are stable SHA-256 values over normalized
planner/action identity. Mutable entries must preserve the planner's exact
identity and, for updates, exactly one planner-selected page ID. Non-mutable
planner results are never converted into mutation actions.

## Orchestration defaults

`OrchestrationConfig()` is inert: schedule and mutation flags both default to
false. An enabled run checks the kill switch before lease acquisition and again
immediately before mutation, validates the exact plan digest, requires a single
lease, and releases that lease on every terminal path after acquisition. The
wrapper composes the mutation adapter; it does not reimplement reconciliation,
identity, pagination, or property mapping.

No scheduler, daemon, background worker, credential source, alert transport, or
production activation is created by this package. Connected execution remains a
separate authorization decision under #736.

## Planner identity and result rules

Drive File ID is authoritative when valid. Drive URL is used only when the
explicit ID is absent and yields one unambiguous supported Drive identity.
Filename never establishes identity. Contradictory or ambiguous evidence fails
closed.

Planner results are `UPDATE_EXISTING`, `CREATE_MISSING`, `DUPLICATE_ID`,
`MALFORMED_IDENTITY`, `CONTRADICTORY_RECORD`, and `EXCLUDED`. Only the first two
are eligible for mutation planning.

`build_reconciliation_plan` remains pure and deterministic. `simulate_apply`
remains in-memory only. Optional read adapters remain separately bounded, and
this repository implementation performs no external write by itself.
