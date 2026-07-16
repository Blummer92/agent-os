# Agent Workflow

## Default Operating Order

1. Read local structured evidence first.
2. Read `evidence_path_summary` in the latest snapshot before escalating.
3. Use the latest snapshot and dependency graph before repeated live lookups.
4. Read proposed-change manifests and validate them against local evidence.
5. Use live systems only when local evidence is missing, stale, contradictory, or a governed gate requires live verification.

## Core Rules

- Prefer snapshots and dependency graphs over repeated searches.
- Treat `placeholder_only` snapshots as fast local context, not proof.
- Never approve destructive changes if records or dependencies are unknown.
- Reuse prior verified mappings only when current evidence still matches.
- Treat missing evidence as `Requires manual review` or `Blocked by missing information`.
- Do not archive, delete, rename, merge, or update Notion data.
- Do not mutate Sheets, Drive, Apps Script, Notion, or production systems.

## Evidence Path Rules

B3 snapshots expose an `evidence_path_summary` at the top level and an
`evidence_path` on each dashboard snapshot.

Agents should use these fields as the first decision point:

```text
mode = placeholder_only
  -> safe for fast agent context
  -> not safe for migration approval
  -> not safe for retirement approval
  -> live verification still required before governed decisions
```

Escalate only when the user needs a migration, retirement, schema, readiness,
approval, source-of-truth, permission, or other governed decision that placeholder
local context cannot support.

## Recommended Sequence

### 1. Refresh Evidence

```bash
python scripts/snapshot_notion.py
```

If live Notion access is unavailable, keep the placeholder output and treat gaps as
blockers rather than proof. In B3, the placeholder output explicitly records that no
network, credentials, cached navigation lookup, or live Notion verification was used.

### 2. Build Dependency Coverage

```bash
python scripts/build_dependency_graph.py --changes proposed_changes/proposed_changes.example.yaml
```

### 3. Validate Proposals

```bash
python scripts/validate_changes.py --changes proposed_changes/proposed_changes.example.yaml
```

### 4. Escalate Only When Needed

Use live lookups only to fill a specific evidence gap, verify stale evidence, resolve
contradictory evidence, or satisfy a governed decision gate. Do not browse broadly
when local files already answer the question.

## Freshness Expectations

- Placeholder snapshots are incomplete evidence.
- Placeholder-only snapshots are not live Notion verification.
- Cached navigation lookup is a future fast path and remains non-authoritative.
- Live verification is required before governed migration or retirement decisions.
- Stale or contradictory graph nodes are unresolved risk.
- Missing dependency coverage blocks destructive approval.
- Evidence quality below verified local coverage stops short of retirement approval.
