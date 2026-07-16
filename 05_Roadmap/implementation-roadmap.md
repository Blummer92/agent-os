# Agent OS Implementation Roadmap

## Purpose

This roadmap is the durable GitHub source of truth for Agent OS Implementation Phase 1. It converts the architecture review and implementation backlog into a staged execution plan for repository work, CI, connector consolidation, and the first governed classroom artifact workflow.

This file is implementation-focused. It does not expand governance, redesign Agent OS, or replace GitHub issues as the work-tracking surface.

## Current Status

- Governance, shared standards, overlays, registries, and the Navigation Alias Registry MVP are stable enough to pause expansion.
- Agent OS has moved from a standards-library phase into Implementation Phase 1.
- The highest-value work is to connect existing tooling into tested, classroom-facing workflows.
- GitHub remains the source of truth for this roadmap, backlog, milestones, tests, tooling, and release sequencing.
- Google Docs or Google Sheets may be used later as dashboard views only, not as the durable source of truth.

## Implementation Phase 1 Goal

Implementation Phase 1 is complete when Agent OS can:

1. run a repo-wide validation gate across structural checks and package tests;
2. report its implementation status honestly in version and validation documents;
3. use one governed read-only connector contract for Notion access;
4. produce one real governed classroom artifact through Workflow Scheduler -> Instructional Materials Coach;
5. retain clear pause boundaries for governance, navigation, and experimental subsystems.

## Epics

### Epic A — Trustworthy Foundation & CI

**Objective:** Create one green repository gate and reconcile status documentation with reality.

**Value:** Protects later refactors, restores trust in repository status, and gives every implementation task a validation baseline.

**Milestone:** M1 — Trustworthy Foundation

### Epic B — Connector Consolidation

**Objective:** Converge fragmented Notion access and connector patterns onto one governed read-only contract.

**Value:** Reduces maintenance cost, prevents divergent adapters, and provides a safer base for future cross-system workflows.

**Milestone:** M2 — Unified Connectors

### Epic C — First Classroom Artifact End-to-End

**Objective:** Run one governed classroom artifact workflow from Workflow Scheduler to Instructional Materials Coach and Google Drive.

**Value:** Converts Agent OS from architecture into observable classroom value.

**Milestone:** M3 — First Classroom Artifact

### Epic D — Packaging & Hygiene

**Objective:** Normalize packaging and remove redundant meta-documentation that slows onboarding.

**Value:** Improves developer experience and reduces repository noise without expanding governance.

**Milestone:** M4 — Hygiene

## Milestones

### M1 — Trustworthy Foundation

**Goal:** Establish an enforced validation baseline and honest status documents.

**Included issue IDs:** A1, A2, A3, A4, A5, D1, D2

**GitHub issues:** #106, #107, #108, #109, #110, #122, #123

**Completion criteria:**

- A single aggregate command runs structural checks and all package tests.
- CI runs that aggregate command on pull requests.
- module-version-map.md, VERSION.md, and VALIDATION_REPORT.md match repository reality.
- agent-memory-context-manager and dashboard-migration-verification have standard packaging.

### M2 — Unified Connectors

**Goal:** Select and implement one governed read-only connector contract.

**Included issue IDs:** B1, B2, B3, B4, B5

**GitHub issues:** #111, #112, #113, #114, #115

**Completion criteria:**

- A connector ADR names the canonical Navigation Registry Read Contract.
- Cached navigation-index lookup and Scheduler live Notion reads remain distinct approved read paths.
- Navigation Registry connector adapters or normalizers bridge cached, live, and placeholder evidence into the canonical contract without creating duplicate Notion clients.
- Dashboard migration, Scheduler, and root navigation skeleton call sites are migrated, wrapped, shimmed, deprecated, or explicitly deferred.
- Tests remain green after migration.

### M3 — First Classroom Artifact

**Goal:** Produce one governed live classroom artifact through Agent OS tooling.

**Included issue IDs:** C1, C2, C3, C4, C5, C6

**GitHub issues:** #116, #117, #118, #119, #120, #121

**Completion criteria:**

- Google OAuth and approved Drive folder requirements are documented.
- Scheduler can invoke a Materials Coach deck-generation step in dry-run mode.
- One live artifact is created in an approved Drive folder with an audit record.
- A sanitized example workflow and repeatable recipe are documented.

### M4 — Hygiene

**Goal:** Reduce redundant repository metadata and strengthen weak package coverage.

**Included issue IDs:** D3, D4

**GitHub issues:** #124, #125

**Completion criteria:**

- Redundant manifest/tree/validation docs are consolidated or pointed to canonical metadata.
- dashboard-migration-verification has meaningful tests for its largest scripts.

## Backlog Issue Map

| ID | GitHub | Issue | Epic | Milestone | Effort | Owner |
|---|---:|---|---|---|---|---|
| A1 | #106 | Add repo-wide aggregate test runner | Foundation & CI | M1 | Small | QA / Test Agent |
| A2 | #107 | CI workflow running the aggregate runner on PRs | Foundation & CI | M1 | Small | GitHub Service Agent |
| A3 | #108 | Reconcile module-version-map.md with disk | Foundation & CI | M1 | Small | Integration Manager |
| A4 | #109 | Correct VERSION.md scope statement | Foundation & CI | M1 | Small | Integration Manager |
| A5 | #110 | Refresh VALIDATION_REPORT.md to current 7 checks | Foundation & CI | M1 | Small | QA / Test Agent |
| B1 | #111 | Connector contract ADR | Connector Consolidation | M2 | Small | Integration Manager |
| B2 | #112 | Reconcile Notion read paths into Navigation Registry evidence bridge | Connector Consolidation | M2 | Medium | Integration Manager |
| B3 | #113 | Define dashboard snapshot Notion evidence path | Connector Consolidation | M2 | Small | Google Workspace Automation Engineer |
| B4 | #114 | Wrap Scheduler Notion reads with Navigation Registry evidence | Connector Consolidation | M2 | Medium | Integration Manager |
| B5 | #115 | Clarify root Notion connector as shim/deprecated skeleton | Connector Consolidation | M2 | Small | Integration Manager |
| C1 | #116 | OAuth setup runbook for Materials Coach | First Classroom Artifact | M3 | Small | Instructional Materials Coach |
| C2 | #117 | Define Scheduler task spec for a deck-generation step | First Classroom Artifact | M3 | Medium | Instructional Materials Coach |
| C3 | #118 | Scheduler to Materials Coach wiring spike, dry-run only | First Classroom Artifact | M3 | Medium | Instructional Materials Coach |
| C4 | #119 | First governed live artifact run | First Classroom Artifact | M3 | Medium | Instructional Materials Coach |
| C5 | #120 | Add example artifact-generation workflow YAML | First Classroom Artifact | M3 | Small | Instructional Materials Coach |
| C6 | #121 | Document the repeatable classroom-artifact recipe | First Classroom Artifact | M3 | Small | Instructional Materials Coach |
| D1 | #122 | Add pyproject.toml to agent-memory-context-manager | Packaging & Hygiene | M1 | Small | Google Workspace Automation Engineer |
| D2 | #123 | Add packaging to dashboard-migration-verification | Packaging & Hygiene | M1 | Small | Google Workspace Automation Engineer |
| D3 | #124 | Consolidate redundant meta docs | Packaging & Hygiene | M4 | Medium | QA / Test Agent |
| D4 | #125 | Test-coverage top-up for dashboard-migration-verification | Packaging & Hygiene | M4 | Medium | QA / Test Agent |

## Dependency Order

1. Start with A1 so the repository has one aggregate validation command.
2. Follow with A2 so the aggregate runner becomes a pull-request gate.
3. Run A3, A5, and A4 to reconcile status and validation documents after the validation baseline exists.
4. Complete D1 and D2 during M1 so all packages can participate consistently in validation.
5. Complete B1 so the canonical Navigation Registry Read Contract is established before connector migration.
6. Complete B2 so the bridge/normalization layer exists before B3, B4, or B5.
7. Complete B3, B4, and B5 after B2 while preserving cached/live/source-of-truth boundaries and avoiding duplicate Notion clients.
8. Complete C1 early because credentials and approved Drive folder access are external dependencies.
9. Complete C2 before C3; complete C3 before C4; complete C4 before C5 and C6.

## Pause Register

The following work remains intentionally paused during Implementation Phase 1 unless a blocker requires revisiting it:

- Governance and standards expansion.
- Navigation Alias Registry expansion.
- Thin placeholder standard domains unless they directly block implementation.
- Workspace Automation Builder live-write expansion.
- Unit Alignment and Teacher Modeling executable stages.
- Agent Memory Manager runtime integration beyond packaging.
- Dashboard Migration Verification feature growth beyond packaging and coverage hygiene.
- Google Docs or Google Sheets roadmap mirrors as source-of-truth records.

## Definition of Implementation Phase 1 Complete

Implementation Phase 1 is complete when:

- M1, M2, and M3 are complete.
- M4 hygiene work is either complete or explicitly deferred with rationale.
- Every pull request can run the repo-wide aggregate validation gate.
- Notion read evidence uses the Navigation Registry Read Contract through approved cached lookup, live read, and adapter/normalization paths without introducing duplicate Notion clients.
- One classroom artifact has been generated through a governed Scheduler -> Materials Coach workflow.
- Roadmap, issue bodies, and status documents agree on what is complete, paused, and deferred.

## Future Recommendations

These ideas are valuable but out of scope for the first 30–90 days:

- Executable Unit Alignment and Teacher Modeling stages.
- Live Workspace write automation through the Apps Script bridge.
- Agent Memory runtime integration with Scheduler.
- Vector database, embeddings, REST API, dashboard, or daemon work.
- Monorepo build tooling beyond the aggregate runner.
- Auto-generated manifests, reading paths, or metadata dashboards.
- Automated Notion-to-Sheet refresh workflows.

## Prepared Labels

The following labels are recommended for GitHub issue organization when label creation is available:

- agent-os
- implementation-phase-1
- epic:foundation
- epic:connectors
- epic:classroom-artifact
- epic:hygiene
- owner:qa-test-agent
- owner:github-service-agent
- owner:integration-manager
- owner:instructional-materials-coach
- owner:google-workspace-automation-engineer

## Notes

- Milestone definitions are listed in this file. If GitHub milestone creation is unavailable through the connector, this file remains the durable milestone source until milestones are created manually or through another authorized GitHub workflow.
- Issue bodies should reference the stable issue IDs above even if GitHub issue numbers differ.
- No implementation work is authorized by this roadmap alone; each issue still requires normal Agent OS ownership, validation, and write authorization handling.
