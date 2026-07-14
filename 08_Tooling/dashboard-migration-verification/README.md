# Dashboard Migration Verification Toolkit

This toolkit gives Agent OS a local, reusable evidence layer for dashboard migration
verification. It reduces repeated live lookup by preferring local registry files,
snapshots, dependency graphs, and validation outputs first.

## Purpose

Use this toolkit to:

- register known dashboard surfaces
- define structured proposed migration changes
- capture local dashboard snapshots
- build reusable dependency graphs
- validate migration proposals conservatively
- produce machine-readable results and human-readable reports

## Safety Boundary

This toolkit is verification-only. It does not archive, delete, rename, merge, or
update Notion data. It does not mutate Google Sheets, Drive, Apps Script, Notion, or
any production system.

Missing evidence is not neutral evidence. Placeholder snapshots are scaffolding, not
proof. If evidence is incomplete, stale, missing, uncertain, or contradictory, classify
as `Requires manual review` or `Blocked by missing information`.

See `01_Shared_Standards/dashboard-governance/dashboard-migration-verification.md` for
the governing standard.

## Expected Structure

```text
08_Tooling/dashboard-migration-verification/
  README.md
  .gitignore
  docs/
    agent_workflow.md
    evidence_model.md
    workspace_commands.md
    workspace_io.md
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

## Commands

Run from this directory:

```bash
python scripts/snapshot_notion.py
python scripts/build_dependency_graph.py --changes proposed_changes/proposed_changes.example.yaml
python scripts/validate_changes.py --changes proposed_changes/proposed_changes.example.yaml
python -m pytest tests
```

## Inputs

- `config/dashboards.yaml`: sanitized combined registry used by the current scripts
- `config/dashboard_registry/*.yaml`: split registry source files for review and maintenance
- `config/dashboards.example.yaml`: minimal example registry fixture
- `config/proposed_changes.schema.json`: schema contract for proposed-change manifests
- `config/schema/*.json`: split schema components for modular schema validation
- `proposed_changes/*.yaml`: proposed migration manifests
- `snapshots/latest.json`: latest local dashboard evidence snapshot
- `graph/dependency_graph.json`: generated dependency graph

## Outputs

- `snapshots/snapshot_<timestamp>.json`: point-in-time local evidence snapshot
- `snapshots/latest.json`: latest snapshot alias
- `graph/dependency_graph.json`: generated dependency graph
- `validation/validation_results.json`: machine-readable validation output
- `validation/validation_report.md`: human-readable validation report

Generated evidence files are intentionally ignored by Git. Commit templates, examples,
schemas, docs, scripts, tests, and `.gitkeep` files only.

## Recommended Run Order

1. Refresh the latest dashboard snapshot.
2. Build the dependency graph from the latest snapshot and target manifest.
3. Validate the proposed changes.
4. Use live systems only if local evidence is missing, stale, or contradictory.

## Ownership

Primary owner: Modeling & Dashboard Governance Agent.

Support:

- QA / Test Agent for validation evidence
- Google Workspace Automation Engineer for Workspace automation boundaries
- GitHub Service Agent for repository implementation
