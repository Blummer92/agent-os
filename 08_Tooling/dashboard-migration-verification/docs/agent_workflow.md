# Agent Workflow

## Default Operating Order

1. Read local structured evidence first.
2. Read `evidence_path_summary` before loading or escalating dashboard evidence.
3. Use the latest snapshot and dependency graph before repeated live lookups.
4. Validate proposed-change manifests against local evidence.
5. Escalate only for a specific evidence gap or governed decision gate.

## Evidence Path Decision

- `placeholder_only`: fast local context only; not migration or retirement proof.
- `cached_navigation_lookup`: routing or identifier evidence; live verification may
  still be required.
- `live_notion_verification`: approved read-only live evidence.
- `mixed` or `unknown`: requires human review before governed decisions.
- `empty`: no dashboards were available for evaluation.

Never infer safety from absent fields. Missing, malformed, contradictory, or
unrecognized evidence metadata fails closed.

## Recommended Sequence

### 1. Refresh Evidence

```bash
python scripts/snapshot_notion.py
```

The default provider is local and placeholder-only. It performs no network call,
requires no credentials, and leaves uncaptured evidence marked `missing`.

### 2. Build Dependency Coverage

```bash
python scripts/build_dependency_graph.py --changes proposed_changes/proposed_changes.example.yaml
```

### 3. Validate Proposals

```bash
python scripts/validate_changes.py --changes proposed_changes/proposed_changes.example.yaml
```

### 4. Escalate Only When Needed

Use cached or live evidence only to resolve a specific gap, stale or contradictory
record, or governed decision requirement. B2 provides evidence normalization; B4
owns the future approved live-read boundary.

## Governing Rules

See `01_Shared_Standards/dashboard-governance/dashboard-migration-verification.md`.
Do not mutate Notion, Sheets, Drive, Apps Script, or production systems from this
workflow.
