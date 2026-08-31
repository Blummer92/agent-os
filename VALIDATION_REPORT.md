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
7. Retired technical agents cannot return as canonical agents, routing primaries/support, or loadout agents; required legacy aliases resolve them to retained canonical owners.
8. Navigation Registry governance and lookup routing remain assigned to ChatGPT Orchestrator, with the Navigation Registry Standard as a non-authoritative support surface.
9. GitHub repository writes and ordinary repository implementation remain assigned to GitHub Service Agent, matching AGENTS access rules and the service overlay's sole-writer role.
10. GitHub Service Agent inherits the Write Authorization Policy and Protected Branch Governance normal PR path.
11. Navigation Registry records remain non-authoritative and cannot grant write permission.
12. Workspace writes remain separately authorized from repository implementation.
13. Missing or malformed tables, governed files, and required invariant sections fail conservatively; validation output is deterministic and non-mutating.

Exact helper-overlay exemptions include the registered helper overlays plus the retired `integration-manager` and `google-workspace-automation-engineer` compatibility files. Those compatibility files are not executable registrations.

Exact Responsibility Matrix support surfaces include Apps Script Sync Test Overlay, Dashboard Builder Overlay, Python Development Overlay, Workspace Implementation Overlay, Python Standards, Google Workspace Standards, Navigation Registry Standard, Reusable Capability Registry Standard, and Source-of-Truth Checks. Support surfaces are valid Matrix values but do not satisfy canonical-agent assignment coverage.

## Semantic Ownership Validation

Implementation: `validate_semantic_ownership()` in `07_Agent_Tests/validate_registry_consistency.py`
Focused tests: `tests/test_registry_consistency.py` (SO-1 through SO-8 fixture matrix)
Status: **advisory only, non-blocking** (#1511). The focused test always passes; findings print to stdout and never fail a caller.

This closes a blind spot the Registry Consistency Audit above does not cover: `validate()` never reads `04_Registry/navigation/**` or any `.yml`/`.yaml` file under `04_Registry/`. `validate_semantic_ownership()` scans three bounded surfaces for two finding types — **stale retired owner** (names a retired technical agent directly, with no resolution through the Legacy Agent Alias Registry) and **unknown canonical owner** (names a value that is neither a current canonical agent, a retired agent, nor a documented support surface):

1. `04_Registry/navigation/**/*.md` — ownership assertions matching `Owner agent: `, `Owned by the `, `governance is owned by the `, or a table row `| Review owner | <value> |`.
2. `04_Registry/lp-reason-code-catalog.yaml` — `semantic_owners[].role` and each family record's `semantic_owner` field.
3. `01_Shared_Standards/instructional-design/lp-reason-code-catalog.md` — the named owners in `## ownership-single-semantic-owner`.

Explicit exclusions: `04_Registry/reusable-capabilities.yml` (already validated by `08_Tooling/reusable-capability-registry/src/reusable_capability_registry/validation.py`, which this validator defers to entirely and never re-flags), `06_Archive/**`, the Legacy Agent Alias Registry's own Alias Table and Ambiguous Legacy Values table, and ordinary prose that resolves a legacy name rather than asserting current ownership.

This validator never modifies an ownership value. Blocking enforcement is a separate, dependent follow-up issue.

## Structural Validation Checks

`07_Agent_Tests/validate-repo-structure.sh` checks:

1. Markdown files over the roughly 200-line maintainability target are reported as a non-blocking advisory unless exempt; line count alone never fails structural validation or authorizes semantic deletion.
2. Every non-helper overlay references `_common-overlay-rules.md`.
3. Governance and Registry top-level filenames do not collide, except `README.md`.
4. Every registered agent has a matching overlay.
5. Every agent test file has a matching overlay.
6. Every overlay has a matching test file.
7. Documentation Dependency Map validation paths exist.
8. Navigation Alias Registry Markdown paths exist.
9. The lean excluded-surface governance baseline remains referenced by its required dependents.

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

## Low-Compute Evidence

- `agent-os-compute-evidence-summary` reports `static`, `focused`, or `aggregate` evidence for one exact plan and head.
- `reused` and `duplicate-no-op` decisions avoid a new build; `stale-skipped` also records zero new builds.
- Aggregate validation should normally run once per exact final head; repetition produces `warning` evidence.
- Only one retry is permitted for the approved transient-infrastructure class; excess retries require `manual-review`.
- Missing build ID, terminal status, machine type, or elapsed seconds remains `unavailable`, never inferred.
- `within-policy` is clean evidence; `warning` needs attention; contradictory or excessive evidence is `manual-review`.
- Evidence is non-authorizing; governance applies, and optional budget alerts require a separate approved handoff with verified project and billing scope—never inferred prices, credentials, IAM steps, or automatic shutdown.
- Rollback removes the compute-evidence module, exports, tests, and this section without external cleanup.
