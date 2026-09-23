# Excluded Surface Baseline

## Purpose

Provide one shared reference for repository work surfaces that remain excluded
unless separately authorized.

## Baseline

Excluded unless separately authorized:

- merge or auto-merge
- issue closure
- direct protected-branch writes
- protected settings, rulesets, or required checks
- GitHub Actions workflow changes
- credentials, secrets, OAuth, IAM, tenant, billing, or permission changes
- production systems
- external-system writes
- governed fields or governed-field mutation
- source-of-truth changes
- classroom artifact routing or storage changes
- persistence paths
- material architecture, ownership, schema, compatibility, authority, workflow,
  protected-setting, production, or external-effect changes
- irreversible actions

## Use

Reference this file from issues, templates, overlays, and shared standards when
the same excluded-surface list would otherwise be repeated.

This file restates existing authorization boundaries. It does not authorize work,
replace live verification, or create a new governance mechanism.

For protected settings, `separately authorized` means the exact mutation needs
its own current repository-owner or governing-path authorization. It does not
require a second execution identity or a generic admin-capable surface after that
authorization exists. The canonical GitHub Service Agent may execute an already-
authorized finite/content-bound protected-setting operation only when the
implementation fixes the repository, target, operation, and changed setting;
binds fresh pre-state; rejects stale, malformed, ambiguous, or expanded input;
performs immediate canonical readback; and has bounded rollback. If any invariant
or required execution capability is absent, the operation remains excluded and
fails closed. Arbitrary ruleset/branch-protection administration, permissions,
credentials, IAM, secrets, workflows, and unrelated protected-setting writes
remain excluded.

## Version

0.2.0

## Changelog

- 0.2.0 clarifies #2644: exact finite protected-setting authorization may execute through the canonical GitHub Service Agent without a redundant second admin surface, while generic administration and missing safety invariants remain excluded.

- 0.1.0 initial shared excluded-surface baseline for #901.
