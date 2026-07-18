# Workspace Commands

Run all commands from `08_Tooling/dashboard-migration-verification/`.

## Refresh Placeholder Snapshot

```bash
python scripts/snapshot_notion.py
```

This writes a local placeholder snapshot to `snapshots/`. It performs no network
call, requires no credentials, and writes to no live system. Read the generated
`evidence_path_summary` before deciding whether escalation is required.

See `evidence_file_reference_runtime.md` for the canonical evidence-path schema and
`evidence_model.md` for tier meanings.

## Build Dependency Graph

```bash
python scripts/build_dependency_graph.py --changes proposed_changes/proposed_changes.example.yaml
```

This reads `snapshots/latest.json` and the target proposed-change manifest, then
writes `graph/dependency_graph.json`.

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

- Cached navigation integration is deferred; B2 already defines normalization.
- Live Notion verification is deferred to the approved B4 read-only boundary.
- Generated evidence files are ignored by Git.
- Missing or placeholder evidence resolves to manual review or blocked results.
