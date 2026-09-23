# Evidence Model

## Purpose

This workspace keeps dashboard-migration evidence in local JSON and YAML files so
agents can reuse prior verified context instead of rediscovering the same dashboard
structure every run.

## File Inventory

See `evidence_file_reference_config.md` for configuration schemas and
`evidence_file_reference_runtime.md` for the canonical runtime schema.

## Evidence Quality Model

Recommended evidence statuses:

- `verified`: locally captured and currently trustworthy
- `inferred`: derived from partial evidence and insufficient for retirement approval
- `stale`: previously captured but needs refresh
- `missing`: not yet captured
- `contradictory`: conflicting local evidence exists

## Evidence Path Tiers

B3 uses **Option D now** and prepares for **Option C later**.

1. `local_placeholder`: fast local context with no network or credentials.
2. `cached_navigation`: future cached lookup through the existing B2 contract
   adapter; useful for routing and identifiers, but not live verification.
3. `live_verified`: future approved read-only verification through the B4 boundary.

Per-dashboard `evidence_path` records provenance and decision safety. The
snapshot-level summary is derived from those records and fails closed when
metadata is missing, malformed, mixed, or unrecognized.

## Safety Model

- Missing evidence is not neutral evidence.
- Placeholder snapshots are scaffolding, not proof.
- Placeholder evidence may support fast context only.
- Migration, retirement, source-of-truth, schema, permission, readiness, and
  approval decisions require the evidence explicitly demanded by the governing
  gate.
- The workspace verifies evidence and never executes live mutations.

See the shared Dashboard Migration Verification Standard for the canonical safety
and classification rules.
