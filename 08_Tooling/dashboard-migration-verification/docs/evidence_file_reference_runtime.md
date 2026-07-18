# Evidence File Reference — Runtime

Companion to `evidence_model.md`. This file is the canonical schema reference for
runtime files under `proposed_changes/`, `snapshots/`, `graph/`, and `validation/`.
See `evidence_file_reference_config.md` for `config/*` files.

## `proposed_changes/*.yaml`

Structured migration proposals consumed by the validation flow. Examples must be
sanitized and must not contain live records or private identifiers.

## `snapshots/*.json`

Structured point-in-time evidence. Placeholder snapshots are local scaffolding,
not live-system proof.

Each dashboard includes its configured registry fields plus an `evidence_path`:

```json
{
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
}
```

The top-level `evidence_path_summary` is derived from dashboard metadata. Its
`mode` is one of `placeholder_only`, `cached_navigation_lookup`,
`live_notion_verification`, `mixed`, `unknown`, or `empty`. Missing, malformed,
or unrecognized evidence paths fail closed as `unknown` or `mixed` and require
human review.

Snapshot consumers must not treat `requires_network=false` or
`requires_credentials=false` as proof that evidence is complete. Decision safety
is controlled by the explicit `safe_for_*` and verification fields.

## `graph/dependency_graph.json`

Derived dependency graph built from the latest snapshot and one proposed-change
manifest. Unknown snapshot fields are additive and do not change graph parsing.

## `validation/validation_results.json`

Machine-readable validation output with change identity, classification,
migration status, risk ratings, blockers, and review reasons.

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

## `validation/validation_report.md`

Human-readable report rendered from `templates/validation_report.md`.
