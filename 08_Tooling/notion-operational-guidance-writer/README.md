# Notion Operational Guidance Writer

Bounded destination-local adapter for Agent OS #1467.

It consumes the existing serialized #1097 `agent-os-coding-command-center-handoff/1.0` contract and projects only:

- `smallest_next_action` → existing Notion `Next Action`
- `primary_blocker` → existing Notion `Blocked Reason` (empty when canonical blocker is absent)

The writer never derives readiness, authorization, blocker ordering, lifecycle state, or next-action semantics. Those remain owned upstream. It resolves exactly one existing `Tasks / Issues` row through exact `Source Link`, verifies the frozen data-source/property types, updates only changed values, reads the row back, and skips an unchanged rerun.

## Safety boundary

- Frozen data source: `5216eacf-639d-4881-92bc-a634ead56669`.
- Writable properties: `Next Action` and `Blocked Reason` only.
- `Source Link`, `Compute Decision`, schema, rows, relations, views, ownership, readiness, approval, priority, and authority are never mutated.
- Missing/duplicate targets, identity mismatch, stale handoff source revision, or schema drift fail closed.
- Repository tests use injected fake clients and perform zero Notion/network I/O.
- Live Notion mutation remains separately authorization-gated; `dry_run=True` is the default.

## Tests

```bash
PYTHONPATH=08_Tooling/notion-operational-guidance-writer/src python -m pytest 08_Tooling/notion-operational-guidance-writer/tests -q
```
