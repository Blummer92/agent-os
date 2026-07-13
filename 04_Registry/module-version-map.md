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
| Google Workspace Standards | 0.1.1 |
| Apps Script Standards | 0.1.0 |
| Notion Standards | 0.2.0 |
| QA/Test Standards | 0.1.0 |
| Dashboard Governance | 0.1.0 |
| Instructional Design Standards | 0.5.0 |
| Agent Orchestrator | 0.1.0 |
| Unit Alignment Agent | 0.3.0 |
| Teacher Modeling Coach | 0.2.0 |
| Instructional Materials Coach | 0.3.0 |
| Student Language Standard | 0.1.0 |
| Workflow Scheduler | 0.6.0 |

**Workflow Scheduler** (`08_Tooling/workflow-scheduler/`) version reflects
six shipped milestones: Phase 1 (MVP), 2A (approval engine), 2B (retry
manager), 2C (pause/resume/cancel lifecycle), 2D (task batching), 2E
(opt-in parallel ready-list dispatch). Current validation: 291 tests
passing, 97% coverage overall. See
`08_Tooling/workflow-scheduler/docs/ARCHITECTURE.md` for implementation
details.
