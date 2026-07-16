# Evidence File Reference — Runtime

Companion to `evidence_model.md`. Schema and field reference for files under
`proposed_changes/`, `snapshots/`, `graph/`, and `validation/`. See
`evidence_file_reference_config.md` for `config/*` files.

### `proposed_changes/*.yaml`

Structured migration proposals consumed by the validation flow. Examples must be
sanitized and must not contain live records or private identifiers.

### `snapshots/*.json`

Structured point-in-time dashboard evidence. Placeholder snapshots are scaffolding only
and do not prove readiness.

B3 adds explicit evidence-path metadata so agents can quickly distinguish local
placeholder context from cached or live verification evidence.

Expected shape:

```json
{
  "generated_at": "...",
  "evidence_path_summary": {
    "mode": "placeholder_only",
    "evidence_speed_tier": "local_placeholder",
    "dashboards_total": 1,
    "dashboards_with_live_verification": 0,
    "dashboards_safe_for_migration_decision": 0,
    "dashboards_safe_for_retirement_decision": 0,
    "requires_network": false,
    "requires_credentials": false,
    "live_verification_required": true
  },
  "dashboards": {
    "example_dashboard": {
      "key": "example_dashboard",
      "name": "Example Dashboard",
      "notion_id": "EXAMPLE_NOTION_ID",
      "data_source_id": "EXAMPLE_DATA_SOURCE_ID",
      "owner": "Dashboard Governance",
      "source_of_truth_role": "example role",
      "retirement_allowed": false,
      "human_approval_required": true,
      "notes": "Example notes.",
      "evidence_path": {
        "mode": "placeholder_only",
        "evidence_speed_tier": "local_placeholder",
        "requires_network": false,
        "requires_credentials": false,
        "cached_navigation_lookup_used": false,
        "live_notion_used": false,
        "contract_normalization_used": false,
        "safe_for_fast_agent_context": true,
        "safe_for_migration_decision": false,
        "safe_for_retirement_decision": false,
        "human_review_required": true,
        "live_verification_required": true,
        "next_required_evidence": "cached_navigation_lookup_then_optional_live_verification"
      },
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

Agents should read `evidence_path_summary` first. Placeholder-only snapshots are safe
for fast context but not for migration approval, retirement approval, or governed
workspace decisions.

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
