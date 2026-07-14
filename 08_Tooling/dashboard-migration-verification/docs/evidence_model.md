# Evidence Model

## Purpose

This workspace keeps dashboard-migration evidence in local JSON and YAML files so
agents can reuse prior verified context instead of rediscovering the same dashboard
structure every run.

## File Inventory

### `config/dashboards.yaml`

Sanitized combined registry for known dashboard surfaces. The current scripts read this
file by default.

Each dashboard entry supports:

- `name`
- `notion_id`
- `data_source_id`
- `owner`
- `source_of_truth_role`
- `retirement_allowed`
- `human_approval_required`
- `notes`

Do not store live private identifiers in committed registry files.

### `config/dashboard_registry/*.yaml`

Split registry source files used for review and maintenance. These files group dashboard
surfaces by operating area while preserving the same dashboard-entry shape as
`config/dashboards.yaml`.

The split registry currently includes:

- `core_dashboards.yaml`
- `operations_dashboards.yaml`
- `coach_and_governance_dashboards.yaml`

### `config/dashboards.example.yaml`

Minimal sanitized registry fixture for tests, examples, or new workspace setup.

### `config/proposed_changes.schema.json`

JSON Schema for proposed-change manifests.

Required fields for each change:

- `action`
- `item_type`
- `source_database`
- `source_item`
- `canonical_database`
- `canonical_item`
- `current_name`
- `proposed_name`
- `migration_method`
- `rollback_method`
- `owner`
- `approval_required`
- `notes`

### `config/schema/*.json`

Split schema components for modular schema review and maintenance. The main schema is
still `config/proposed_changes.schema.json` unless tooling is explicitly switched to the
split-schema entry point.

### `proposed_changes/*.yaml`

Structured migration proposals consumed by the validation flow. Examples must be
sanitized and must not contain live records or private identifiers.

### `snapshots/*.json`

Structured point-in-time dashboard evidence. Placeholder snapshots are scaffolding only
and do not prove readiness.

Expected shape:

```json
{
  "generated_at": "...",
  "placeholder": true,
  "dashboards": {
    "example_dashboard": {
      "name": "Example Dashboard",
      "notion_id": "EXAMPLE_NOTION_ID",
      "data_source_id": "EXAMPLE_DATA_SOURCE_ID",
      "schema": {},
      "views": {},
      "templates": {},
      "permissions": {},
      "automations": {},
      "buttons": {},
      "records_summary": {},
      "records_sample": []
    }
  }
}
```

### `graph/dependency_graph.json`

Derived dependency graph built from the latest snapshot and one proposed-change
manifest.

Covered dependency types include fields, status values, formulas, relations, rollups,
linked views, templates, buttons, automations, permissions, documentation references,
agent references, and synced databases.

### `validation/validation_results.json`

Machine-readable validation output. Each result includes change identity fields,
classification, migration status, risk ratings, blockers, and review reasons.

Classifications:

- `Safe to automate`
- `Requires manual review`
- `Blocked by missing information`

Migration statuses:

- `Safe to Retire`
- `Requires Record Migration`
- `Requires Field Migration`
- `Requires View Migration`
- `Requires Dependency Cleanup`
- `Requires Manual Review`

### `validation/validation_report.md`

Human-readable report rendered from `templates/validation_report.md`.

## Evidence Quality Model

Recommended evidence statuses:

- `verified`: locally captured and currently trustworthy
- `inferred`: derived from partial evidence and not sufficient for retirement approval
- `stale`: previously captured but needs refresh
- `missing`: not yet captured
- `contradictory`: conflicting local evidence exists

## Safety Model

- Missing evidence is not neutral evidence.
- Placeholder snapshots are scaffolding, not proof.
- Unknown records, dependencies, templates, buttons, permissions, and synced databases
  prevent destructive approval.
- Similarly named dashboards and fields must still be proven equivalent.
- The workspace supports verification only and does not execute live mutations.
