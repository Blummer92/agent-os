# Evidence Model

## Purpose

This workspace keeps dashboard-migration evidence in local JSON and YAML files so
agents can reuse prior verified context instead of rediscovering the same dashboard
structure every run.

## File Inventory

See `evidence_file_reference_config.md` for the full per-file schema and required
fields for every file under `config/`, and `evidence_file_reference_runtime.md`
for `proposed_changes/`, `snapshots/`, `graph/`, and `validation/` files.

## Evidence Quality Model

Recommended evidence statuses:

- `verified`: locally captured and currently trustworthy
- `inferred`: derived from partial evidence and not sufficient for retirement approval
- `stale`: previously captured but needs refresh
- `missing`: not yet captured
- `contradictory`: conflicting local evidence exists

## Snapshot Evidence Path Model

B3 snapshots use a fast local evidence path by default. The placeholder provider
adds `evidence_path` to each dashboard and `evidence_path_summary` to the top-level
snapshot so agents can decide whether the snapshot is enough for quick context or
whether escalation is required.

The current B3 path is:

```text
Option D now: local placeholder evidence only
Option C later: cached navigation lookup, then optional live verification
```

In placeholder mode:

- `mode` is `placeholder_only`
- `evidence_speed_tier` is `local_placeholder`
- `requires_network` is `false`
- `requires_credentials` is `false`
- `live_notion_used` is `false`
- `cached_navigation_lookup_used` is `false`
- `safe_for_fast_agent_context` is `true`
- `safe_for_migration_decision` is `false`
- `safe_for_retirement_decision` is `false`
- `live_verification_required` is `true`

Agents should read `evidence_path` and `evidence_path_summary` before escalating.
Fast local context is allowed from placeholder snapshots, but migration approval,
retirement approval, source-of-truth decisions, and governed workspace changes still
require cached lookup and/or live verification through approved future paths.

## Safety Model

- Missing evidence is not neutral evidence.
- Placeholder snapshots are scaffolding, not proof.
- Placeholder-only snapshots do not prove live Notion state.
- Placeholder-only snapshots do not permit migration or retirement decisions.
- Unknown records, dependencies, templates, buttons, permissions, and synced databases
  prevent destructive approval.
- Similarly named dashboards and fields must still be proven equivalent.
- The workspace supports verification only and does not execute live mutations.
