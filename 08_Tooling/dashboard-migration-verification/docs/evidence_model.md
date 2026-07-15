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

## Safety Model

- Missing evidence is not neutral evidence.
- Placeholder snapshots are scaffolding, not proof.
- Unknown records, dependencies, templates, buttons, permissions, and synced databases
  prevent destructive approval.
- Similarly named dashboards and fields must still be proven equivalent.
- The workspace supports verification only and does not execute live mutations.
