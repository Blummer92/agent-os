# Evidence Path Snapshot Example

Companion example for `evidence_file_reference_runtime.md`.

B3 placeholder snapshots include explicit evidence-path metadata so agents can
distinguish fast local context from cached or live verification evidence.

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

Placeholder-only snapshots are safe for fast context only. They are not migration
approval, retirement approval, or governed workspace-decision evidence. They use
no network, no credentials, and no live Notion read. Live verification remains
required for governed decisions.
