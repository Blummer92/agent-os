# Workspace Inputs And Outputs

## Expected Inputs

- `config/dashboards.example.yaml`: sanitized registry example for dashboard surfaces.
- `config/proposed_changes.schema.json`: schema contract for proposed changes.
- `proposed_changes/*.yaml`: structured migration proposals.
- `snapshots/latest.json`: latest local evidence snapshot.
- `graph/dependency_graph.json`: dependency graph built from local evidence.

## Outputs

- `snapshots/snapshot_<timestamp>.json`: point-in-time local evidence snapshot.
- `snapshots/latest.json`: latest snapshot alias.
- `graph/dependency_graph.json`: dependency graph with risk metadata.
- `validation/validation_results.json`: machine-readable validation results.
- `validation/validation_report.md`: human-readable validation report.

## Commit Rules

Commit examples, schemas, templates, scripts, docs, tests, and `.gitkeep` files only.
Do not commit live snapshots, validation outputs, private dashboard records, Notion IDs,
Google Sheet records, or production workbook data.
