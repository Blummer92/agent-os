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
| Instructional Design Standards | 0.6.0 |
| Agent Orchestrator | 0.1.0 |
| Unit Alignment Agent | 0.3.0 |
| Teacher Modeling Coach | 0.2.0 |
| Instructional Materials Coach | 0.3.0 |
| Student Language Standard | 0.3.0 |
| Workflow Scheduler | 0.9.0 |
| Workspace Automation Builder Tooling | 0.1.1 |
| Agent Memory & Context Budget Manager | 0.1.0 |
| IA4D-to-Scheduler Handoff Contract | 0.2.0 |
| GitHub Issue Lifecycle Standard | 0.1.0 |
| Agent OS Execution Service | 0.4.0 |
| Artifact-First Response Standard | 0.1.0 |
| Teacher Decision Studio Standard | 0.1.0 |

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

**Workflow Scheduler**, **Agent Memory & Context Budget Manager**,
**IA4D-to-Scheduler Handoff Contract**, and **Agent OS Execution Service**
extended descriptions moved to `04_Registry/module-version-map-details.md` to
keep this index under the line-limit. Workflow Scheduler remains `0.9.0`;
Agent OS Execution Service remains `0.4.0`.

**Artifact-First Response Standard**
(`01_Shared_Standards/instructional-design/artifact-first-response-standard.md`,
#821) requires classroom-material responses to lead with the requested
artifact, preview, or content specification before backend routing and
governance reporting, while preserving all existing gate, ownership, and
stop-condition behavior.

**Teacher Decision Studio Standard**
(`01_Shared_Standards/instructional-design/teacher-decision-studio-standard.md`
plus `teacher-decision-studio-previews-standard.md`, #823/#824) defines a
table-first rubric/assessment consultation protocol -- comparison table,
format catalog, explanation-risk analysis, and per-option in-chat and PDF
worksheet previews -- that recommends without auto-approving and never writes
a governed field without explicit teacher confirmation.

## Reconciliation Notes

A3 reviewed this map against visible repository evidence only. Any runtime status
not directly supported by files or validation evidence remains intentionally
unstated rather than inferred.
