# Evidence File Reference — Runtime

Companion to `evidence_model.md`. Schema and field reference for files under
`proposed_changes/`, `snapshots/`, `graph/`, and `validation/`. See
`evidence_file_reference_config.md` for `config/*` files.

### `proposed_changes/*.yaml`

Structured migration proposals consumed by the validation flow. Examples must be
sanitized and must not contain live records or private identifiers.

### `snapshots/*.json`

Structured point-in-time dashboard evidence. Placeholder snapshots are scaffolding
only and do not prove readiness.

B3 adds explicit evidence-path metadata so agents can distinguish local
placeholder context from cached or live verification evidence.

Runtime snapshots include:

- top-level `evidence_path_summary`
- per-dashboard `evidence_path`
- registry fields preserved in each dashboard snapshot
- missing evidence sections for schema, views, templates, permissions,
  automations, and buttons

Agents should read `evidence_path_summary` first. Placeholder-only snapshots are
safe for fast context but not for migration approval, retirement approval, or
governed workspace decisions.

Placeholder-only evidence means:

- no network was used
- no credentials were used
- no live Notion read occurred
- cached navigation lookup was not used
- live verification remains required for governed decisions

See `evidence_path_snapshot_example.md` for the expanded JSON example.

### `graph/dependency_graph.json`

Derived dependency graph built from the latest snapshot and one proposed-change
manifest.

Covered dependency types include fields, status values, formulas, relations,
rollups, linked views, templates, buttons, automations, permissions,
documentation references, agent references, and synced databases.

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
