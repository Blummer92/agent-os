# Directory Structure

Companion to `../README.md`. Expected layout for
`08_Tooling/dashboard-migration-verification/`:

```text
08_Tooling/dashboard-migration-verification/
  README.md
  .gitignore
  docs/
    agent_workflow.md
    evidence_model.md
    evidence_file_reference_config.md
    evidence_file_reference_runtime.md
    workspace_commands.md
    workspace_io.md
    directory_structure.md
  config/
    dashboards.yaml
    dashboards.example.yaml
    dashboard_registry/
      coach_and_governance_dashboards.yaml
      core_dashboards.yaml
      operations_dashboards.yaml
    proposed_changes.schema.json
    schema/
      proposed_change.definition.json
      proposed_change.enums.json
      proposed_changes.meta.json
  proposed_changes/
    proposed_changes.example.yaml
  snapshots/
    .gitkeep
  graph/
    .gitkeep
  validation/
    .gitkeep
  scripts/
    dashboard_migration_common.py
    snapshot_notion.py
    build_dependency_graph.py
    validate_changes.py
  templates/
    validation_report.md
  tests/
    test_dependency_graph.py
    test_validate_changes.py
```

Generated evidence files are intentionally ignored by Git. Commit templates,
examples, schemas, docs, scripts, tests, and `.gitkeep` files only.
