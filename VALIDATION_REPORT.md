# Validation Report

## Current Baseline

- Review root: `Blummer92/agent-os`
- Baseline branch: `main`
- Scope: Agent OS repository-wide validation after A2 and A3
- Primary command: `./scripts/validate-all.sh`
- Structural command: `bash 07_Agent_Tests/validate-repo-structure.sh`
- CI gate: `Agent OS Validation Gate` on the self-hosted `agent-os` runner
- Latest evidence used for this refresh: PR #144 / A3 validation passed before merge

## Structural Validation Checks

`07_Agent_Tests/validate-repo-structure.sh` now runs structural and registry-consistency checks:

1. All non-exempt Markdown files, except `CLAUDE.md`, are under 100 lines.
2. Every overlay references `_common-overlay-rules.md`.
3. No filename collisions exist between `00_Governance/` and `04_Registry/`, except each folder's own `README.md`.
4. Every registered agent has a matching overlay file.
5. Every registered agent has a matching test file.
6. Every agent test file has a matching overlay.
7. Every overlay has a matching test file.
8. Every overlay is registered or explicitly exempted.
9. Overlay inherited standard paths exist.
10. Responsibility Matrix primary agents are registered.
11. Responsibility Matrix support values resolve.
12. Every registered agent appears in the Responsibility Matrix.
13. Navigation Registry ownership and write boundary remain consistent.
14. All Documentation Dependency Map metadata paths exist.

Expected structural result on a clean baseline: 14 passed, 0 failed.

## Aggregate Validation Coverage

`scripts/validate-all.sh` runs structural validation first, then discovers pytest
test directories and runs each Python test suite. The runner reports commands
executed, check results, failed packages, overall status, and exit code.

Current package suites are discovered from repository `tests` directories with
Python test files. Suites with `src/` are run with `PYTHONPATH=src`; root tests
run from the repository root.

## Current Evidence

- PR #142 / A2 passed the Agent OS Validation Gate before merge.
- PR #144 / A3 passed the Agent OS Validation Gate before merge.
- Navigation Registry Offline Tests passed for PR #144.
- No failed or skipped checks are recorded for the current A3 baseline evidence.

## Boundaries

This report records validation evidence only. It does not authorize issue-to-PR
automation, live Google Drive writes, Notion writes, production writes,
readiness-field changes, sharing changes, or source-of-truth changes.

## Reproducibility

To reproduce the current validation baseline from a clean checkout:

```bash
./scripts/validate-all.sh
```

For pull requests, use the `Agent OS Validation Gate` and require the self-hosted
`agent-os` runner to complete successfully before merge.

## Remaining Follow-Up

- A4 / #109 still needs to update `VERSION.md` so release scope matches the
  reconciled module map and validation baseline.
- D1 / #122 and D2 / #123 remain packaging follow-ups for M1.
