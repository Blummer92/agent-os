# Legacy Issue Metadata Migration

Issue: #2016

## Purpose

`legacy_migration.py` provides the governed, fail-closed migration seam for Agent OS issues that predate the canonical tiered issue form.

The migration helper does **not** infer metadata from free-form prose, issue titles, labels, age, or repository state. The caller must supply explicit canonical evidence for:

- issue tier;
- primary owner;
- readiness candidate;
- source of truth; and
- external-write boundary.

Work type is optional.

## Contract

`build_legacy_issue_migration(...)` is side-effect free. It returns either:

- `migrated` with a body whose canonical metadata block is appended last;
- `already-canonical` when the supplied body already has a complete tiered contract; or
- `manual-review` with deterministic reason codes when evidence is missing, ambiguous, multiline, outside the current tiered issue-form vocabulary, unmapped by the label map, or when partial canonical metadata already exists.

The helper never writes an issue body or labels and reports `mutation_performed=False`.

The rendered metadata block uses the existing canonical headings consumed by `parse_issue_form_body()`. After an authorized caller persists the migrated body, the existing `reconcile_issue_labels()` path remains the sole readiness/managed-label projection owner. No second readiness authority, selector, or label writer is introduced.

## Trailing-content invariant

Legacy prose is preserved byte-for-byte except for trailing whitespace normalization at the append boundary. The canonical metadata block is always rendered after the legacy body, and metadata values containing newline characters are rejected. This prevents prose after the final metadata field from being absorbed into `external-write` or another canonical value.

## Validation

Focused regression coverage is in:

```bash
python -m pytest tests/agent_os_issue_labels/test_legacy_migration.py -q
```

The tests include a real legacy issue shape derived from #1944, insufficient evidence, trailing legacy content, partial canonical metadata, a retired owner alias, and multiline injection evidence. The real-shape case also feeds the migrated body into the existing `reconcile_issue_labels()` dry-run path to prove the canonical readiness projection remains unchanged.

Repository acceptance still requires the normal exact-head aggregate validation for the pull request.

## Authorization boundary

This helper is not body-write, readiness, merge, closure, workflow, production, or external-write authority. Any later GitHub mutation remains subject to the existing GitHub Service Agent, Safe Implementation Lane, issue-label reconciliation, and excluded-surface contracts.
