# Module Version Map

Module versions are governed by `00_Governance/standards-change-control.md`.
Repository releases and module versions are versioned independently, so module
versions change only when the module's standards or contract changes.

| Module | Version |
|---|---|
| Global Engineering | 0.1.0 |
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
| Workflow Scheduler | 0.6.0 |
| Workspace Automation Builder Tooling | 0.1.1 |
| Agent Memory & Context Budget Manager | 0.0.0 |

**Dashboard Migration Verification**
(`08_Tooling/dashboard-migration-verification/`) starts as a verification-only
migration evidence toolkit for dashboard registry examples, placeholder snapshots,
dependency graphs, conservative validation results, and human-readable reports. It
never authorizes live Notion, Workspace, trigger, sharing, source-of-truth, or
production dashboard writes.

**Workspace Automation Builder Tooling**
(`08_Tooling/workspace-automation-builder/`) includes an Apps Script safety
bridge, offline test suite, sync safety docs, sanitized sample handoff fixture,
JSON schemas, validation fixtures, and a local-only fixture validator. It does
not authorize live Workspace, Notion, trigger, sharing, or production writes.

**Workflow Scheduler** (`08_Tooling/workflow-scheduler/`) version reflects
thirteen shipped milestones: Phase 1 (MVP), 2A (approval engine), 2B (retry
manager), 2C (pause/resume/cancel lifecycle), 2D (task batching), 2E
(opt-in parallel ready-list dispatch), 3A (GitHub read-only adapter), 3B
(Notion read-only adapter), 3C (GitHub approved comment adapter), 3D
(five-state result contract), 3E (GitHub approved label adapter), 3F
(adapter contract migration). Current validation: 612 tests passing, 96%
coverage overall. Real adapters use five-state contract; noop/fakes still
cover legacy shape. See `08_Tooling/workflow-scheduler/docs/ARCHITECTURE.md`
for implementation details.

**Agent Memory & Context Budget Manager**
(`08_Tooling/agent-memory-context-manager/`) is registered as planning-track
complete, implementation not started. Current phase: Memory 0F. Shipped
planning milestones: 0A design README, 0B handoff packet template, 0C context
budget policy, 0D summary cache format, and 0E Scheduler integration design.
Current files: `README.md`, `HANDOFF_PACKET_TEMPLATE.md`,
`CONTEXT_BUDGET_POLICY.md`, `SUMMARY_CACHE_FORMAT.md`, and
`SCHEDULER_INTEGRATION_DESIGN.md`. Unsupported: implementation code, Python
module, Scheduler integration, autonomous writes, vector DB, embeddings, REST
API, dashboard, daemon, and production deployment.
