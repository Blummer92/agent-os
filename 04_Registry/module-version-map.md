# Module Version Map

Module versions are governed by `00_Governance/standards-change-control.md`.
Repository releases and module versions are versioned independently, so module
versions change only when the module's standards or contract changes.

| Module | Version |
|---|---|
| Global Engineering | 0.2.0 |
| Read-Only Default | 0.1.0 |
| Source-of-Truth Checks | 0.1.0 |
| Python Standards | 0.1.0 |
| Google Workspace Standards | 0.1.2 |
| Apps Script Standards | 0.1.0 |
| Notion Standards | 0.2.0 |
| QA/Test Standards | 0.1.0 |
| Dashboard Governance | 0.1.0 |
| Dashboard Migration Verification | 0.1.0 |
| Instructional Design Standards | 0.5.0 |
| Agent Orchestrator | 0.1.0 |
| Unit Alignment Agent | 0.3.0 |
| Teacher Modeling Coach | 0.2.0 |
| Instructional Materials Coach | 0.3.0 |
| Student Language Standard | 0.1.0 |
| Workflow Scheduler | 0.7.0 |
| Workspace Automation Builder Tooling | 0.1.1 |
| Agent Memory & Context Budget Manager | 0.1.0 |
| IA4D-to-Scheduler Handoff Contract | 0.2.0 |

**Dashboard Migration Verification**
(`08_Tooling/dashboard-migration-verification/`) starts as a verification-only
migration evidence toolkit for dashboard registry examples, placeholder snapshots,
dependency graphs, conservative validation results, and human-readable reports. It
never authorizes live Notion, Workspace, trigger, sharing, source-of-truth, or
production dashboard writes. Standard packaging metadata was completed by D2 (#123).

**Workspace Automation Builder Tooling**
(`08_Tooling/workspace-automation-builder/`) includes an Apps Script safety
bridge, offline test suite, sync safety docs, sanitized sample handoff fixture,
JSON schemas, validation fixtures, and a local-only fixture validator. It does
not authorize live Workspace, Notion, trigger, sharing, or production writes.

**Workflow Scheduler** (`08_Tooling/workflow-scheduler/`) version reflects
fourteen shipped milestones: Phase 1 (MVP), 2A (approval engine), 2B (retry
manager), 2C (pause/resume/cancel lifecycle), 2D (task batching), 2E
(opt-in parallel ready-list dispatch), 3A (GitHub read-only adapter), 3B
(Notion read-only adapter), 3C (GitHub approved comment adapter), 3D
(five-state result contract), 3E (GitHub approved label adapter), 3F
(adapter contract migration), and WSC3 (stateless draft-proposal ingestion).
WSC3 validates supplied WSC1, IssuePlanCore, and GEX evidence and emits only
immutable, unapproved proposal evidence. It does not create tasks, approvals,
queues, leases, workers, dispatch state, persistence, or external I/O. See
`08_Tooling/workflow-scheduler/docs/ARCHITECTURE.md` for implementation details.

**Agent Memory & Context Budget Manager**
(`08_Tooling/agent-memory-context-manager/`) has moved beyond planning-only
status. Current disk evidence includes standard packaging metadata completed by
D1 (#122), a local Python module under `src/`, and pytest coverage under `tests/`
for handoff packet construction and validation, cache-key generation, packet
summaries, summary cache read/write helpers, summary cache lookup, and
packet-to-cache writing. Current phase evidence reaches Memory 1G local
summary-cache write-from-packet helpers.

Still unsupported or incomplete: Scheduler runtime integration, autonomous
writes, vector DB, embeddings, REST API, dashboard, daemon, and production
deployment. The planning documents remain part of the module: `README.md`,
`HANDOFF_PACKET_TEMPLATE.md`, `CONTEXT_BUDGET_POLICY.md`,
`SUMMARY_CACHE_FORMAT.md`, and `SCHEDULER_INTEGRATION_DESIGN.md`.

**IA4D-to-Scheduler Handoff Contract**
(`00_Governance/architecture-decisions/adr-0002-ia4d-scheduler-handoff-contract.md`
plus its `adr-0002-details-*` companions) remains version `0.2.0`. WSC1 implements
that existing contract in
`scripts/agent_os_issue_acceptance/scheduler_handoff.py`, supporting
`contract_version=0.2.0` and `planning_result_version=0.1.0`. The implementation
performs pure local serialization, digesting, and validation only; it does not
establish freshness, authorize execution, or change Workflow Scheduler runtime.
Future version changes require an approved standards or contract change under
`00_Governance/standards-change-control.md`.

## Reconciliation Notes

A3 reviewed this map against visible repository evidence only. Any runtime status
not directly supported by files or validation evidence remains intentionally
unstated rather than inferred.
