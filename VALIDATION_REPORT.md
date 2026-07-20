# Validation Report

## Current Baseline

- Review root: `Blummer92/agent-os`
- Documentation baseline: current `main`
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
4. Matrix primary agents are registered, and every canonical agent has an exact Primary or Support assignment.
5. Matrix support values are registered agents or exact governed support surfaces.
6. Unknown values, routing placeholders, legacy aliases, and near matches do not pass as canonical agents.
7. Navigation Registry responsibilities keep Integration Manager as primary and inheriting the Navigation Registry Standard.
8. GitHub repository writes remain assigned to GitHub Service Agent, matching AGENTS access rules and the service overlay's sole-writer role.
9. GitHub Service Agent inherits the Write Authorization Policy and Protected Branch Governance normal PR path.
10. Navigation Registry records remain non-authoritative and cannot grant write permission.
11. Integration Manager retains navigation governance without direct GitHub write authority.
12. Missing or malformed tables, governed files, and required invariant sections fail conservatively.
13. Validation output is deterministic and does not mutate repository content.

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

Support surfaces are valid Matrix values but do not satisfy canonical-agent assignment coverage. Write-boundary checks use scoped headings, stable paths, and ownership tuples instead of full-paragraph matching. Future schema or exemption changes require matching parser and regression-test updates.

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

- all duplicated policy text has been removed beyond the common-overlay reference check;
- every possible repository reference exists outside the implemented path checks.

Policy deduplication remains an inheritance-first governance expectation in `00_Governance/ownership-and-source-of-truth.md`. Parent issue #203 owns the implement-or-accept decision for remaining non-automated expectations.

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
