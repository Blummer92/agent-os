# Validation Report

## Current Baseline

- Review root: `Blummer92/agent-os`
- Documentation baseline: `main` at `81801313fa16bfbea9203755345d7cc5250091f9`
- Primary command: `./scripts/validate-all.sh`
- Structural command: `bash 07_Agent_Tests/validate-repo-structure.sh`
- Registry audit command: `python -m pytest tests/test_registry_consistency.py`
- Python: 3.11 with `pytest` installed
- Exercised platform: Linux; Windows and macOS are unverified supplemental environments

## Registry Consistency Audit

Implementation: `07_Agent_Tests/validate_registry_consistency.py`
Focused tests: `tests/test_registry_consistency.py`
Aggregate path: root pytest discovery through `scripts/validate-all.sh`

The audit automatically checks:

1. Registered agents have matching overlays and agent test files.
2. Overlays are registered or match an exact helper-overlay exemption.
3. Backticked governed paths under `00_Governance/`, `01_Shared_Standards/`, and `04_Registry/` exist.
4. Responsibility Matrix primary agents are registered.
5. Responsibility Matrix support values are registered agents or exact governed support surfaces.
6. Unknown values, routing placeholders, legacy aliases, and near matches do not pass as canonical Matrix agents.
7. Navigation Registry responsibility rows keep Integration Manager as primary.
8. Integration Manager inherits the Navigation Registry Standard.
9. Missing, empty, or malformed registry and Matrix tables and rows fail conservatively.
10. Validation output is deterministic and does not mutate repository content.

Exact helper-overlay exemptions:

- `apps-script-sync-test-overlay`
- `dashboard-builder-overlay`
- `python-development-overlay`
- `workspace-implementation-overlay`

Exact Responsibility Matrix support surfaces:

- `Apps Script Sync Test Overlay`
- `Dashboard Builder Overlay`
- `Python Development Overlay`
- `Workspace Implementation Overlay`

Future schema or exemption changes require matching parser and regression-test updates.

## Structural Validation Checks

`07_Agent_Tests/validate-repo-structure.sh` checks:

1. Non-exempt Markdown files, except `CLAUDE.md`, are under 100 lines.
2. Every non-helper overlay references `_common-overlay-rules.md`.
3. Governance and Registry top-level filenames do not collide, except `README.md`.
4. Every registered agent has a matching overlay.
5. Every agent test file has a matching overlay.
6. Every overlay has a matching test file.
7. Documentation Dependency Map validation paths exist.

## Coverage Limits

A green run does not automatically prove:

- every canonical agent has a Responsibility Matrix entry or documented exemption;
- GitHub Service Agent sole-write ownership remains intact;
- cached Navigation Registry data remains non-authoritative and cannot grant write permission;
- all duplicated policy text has been removed beyond the common-overlay reference check;
- every possible repository reference exists outside the implemented path checks.

GitHub write ownership is governed by `AGENTS.md` and `02_Agent_Overlays/github-service-agent.md`.
The non-authoritative registry boundary is governed by `01_Shared_Standards/navigation/navigation-registry-standard.md`.
Policy deduplication remains an inheritance-first governance expectation in `00_Governance/ownership-and-source-of-truth.md`.
Parent issue #203 owns the implement-or-accept decision for remaining non-automated expectations after #208.

## Reproducibility

Record the exact tested commit SHA and run:

```bash
bash 07_Agent_Tests/validate-repo-structure.sh
python -m pytest tests/test_registry_consistency.py
./scripts/validate-all.sh
```

The aggregate runner requires Python and `pytest`, runs structural validation first, then discovers and executes Python test suites. Record commands, exit codes, focused-test totals, aggregate results, operating system, and Python version.

## Boundaries

Validation results are evidence only. They do not authorize writes, readiness or approval changes, ownership changes, registry edits, source-of-truth changes, production changes, GitHub label or PR-state mutation, branch-protection changes, or automatic merging.
