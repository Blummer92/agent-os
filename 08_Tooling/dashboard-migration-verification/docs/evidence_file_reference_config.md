# Evidence File Reference — Config

Companion to `evidence_model.md`. Schema and field reference for files under
`config/`. See `evidence_file_reference_runtime.md` for `proposed_changes/`,
`snapshots/`, `graph/`, and `validation/` files.

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
