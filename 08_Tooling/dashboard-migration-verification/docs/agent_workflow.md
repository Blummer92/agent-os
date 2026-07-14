# Agent Workflow

## Default Operating Order

1. Read local structured evidence first.
2. Use the latest snapshot and dependency graph before repeated live lookups.
3. Read proposed-change manifests and validate them against local evidence.
4. Use live systems only when local evidence is missing, stale, or contradictory.

## Core Rules

- Prefer snapshots and dependency graphs over repeated searches.
- Never approve destructive changes if records or dependencies are unknown.
- Reuse prior verified mappings only when current evidence still matches.
- Treat missing evidence as `Requires manual review` or `Blocked by missing information`.
- Do not archive, delete, rename, merge, or update Notion data.
- Do not mutate Sheets, Drive, Apps Script, Notion, or production systems.

## Recommended Sequence

### 1. Refresh Evidence

```bash
python scripts/snapshot_notion.py
```

If live Notion access is unavailable, keep the placeholder output and treat gaps as
blockers rather than proof.

### 2. Build Dependency Coverage

```bash
python scripts/build_dependency_graph.py --changes proposed_changes/proposed_changes.example.yaml
```

### 3. Validate Proposals

```bash
python scripts/validate_changes.py --changes proposed_changes/proposed_changes.example.yaml
```

### 4. Escalate Only When Needed

Use live lookups only to fill a specific evidence gap, verify stale evidence, or resolve
contradictory evidence. Do not browse broadly when local files already answer the
question.

## Freshness Expectations

- Placeholder snapshots are incomplete evidence.
- Stale or contradictory graph nodes are unresolved risk.
- Missing dependency coverage blocks destructive approval.
- Evidence quality below verified local coverage stops short of retirement approval.
