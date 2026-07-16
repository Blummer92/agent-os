# Workspace Commands

Run all commands from `08_Tooling/dashboard-migration-verification/`.

## Refresh Placeholder Snapshot

```bash
python scripts/snapshot_notion.py
```

This writes a local placeholder snapshot to `snapshots/`. It does not connect to Notion
or write to live systems.

The B3 placeholder snapshot includes:

- top-level `evidence_path_summary`
- per-dashboard `evidence_path`
- explicit `requires_network=false`
- explicit `requires_credentials=false`
- explicit `live_notion_used=false`
- explicit `safe_for_migration_decision=false`
- explicit `safe_for_retirement_decision=false`

Use this output for fast local agent context only. Do not treat it as migration,
retirement, schema, readiness, approval, or source-of-truth proof.

## Build Dependency Graph

```bash
python scripts/build_dependency_graph.py --changes proposed_changes/proposed_changes.example.yaml
```

This reads `snapshots/latest.json` and the target proposed-change manifest, then writes
`graph/dependency_graph.json`.

## Validate Changes

```bash
python scripts/validate_changes.py --changes proposed_changes/proposed_changes.example.yaml
```

This writes `validation/validation_results.json` and
`validation/validation_report.md`.

## Run Tests

```bash
python -m pytest tests
```

## Notes

- Live Notion connectivity is intentionally not wired in this scaffold.
- Cached navigation lookup is a future fast path and remains non-authoritative.
- Generated evidence files are ignored by Git.
- Missing or placeholder evidence should resolve to manual review or blocked results.
