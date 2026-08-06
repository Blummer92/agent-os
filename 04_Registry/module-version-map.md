# Module Version Map

Module versions are governed by `00_Governance/standards-change-control.md`.
Repository releases and module versions are versioned independently, so module
versions change only when the module's standards or contract changes.

| Module | Version |
|---|---|
| Global Engineering | 0.3.0 |
| Read-Only Default | 0.1.0 |
| Source-of-Truth Checks | 0.1.0 |
| Python Standards | 0.1.0 |
| Google Workspace Standards | 0.1.2 |
| Apps Script Standards | 0.1.0 |
| Notion Standards | 0.3.0 |
| QA/Test Standards | 0.1.0 |
| Dashboard Governance | 0.1.0 |
| Dashboard Migration Verification | 0.1.0 |
| Instructional Design Standards | 0.7.0 |
| Agent Orchestrator | 0.1.0 |
| Unit Alignment Agent | 0.3.0 |
| Teacher Modeling Coach | 0.2.0 |
| Instructional Materials Coach | 0.3.0 |
| Student Language Standard | 0.3.0 |
| Workflow Scheduler | 0.9.1 |
| Workspace Automation Builder Tooling | 0.1.1 |
| Agent Memory & Context Budget Manager | 0.1.0 |
| IA4D-to-Scheduler Handoff Contract | 0.2.0 |
| GitHub Issue Lifecycle Standard | 0.1.0 |
| Agent OS Execution Service | 0.5.0 |
| Artifact-First Response Standard | 0.1.0 |
| Teacher Decision Studio Standard | 0.1.0 |
| LP Pacing Handoff Contract | 0.1.0 |
| LP Reason Code Catalog | 0.1.0 |
| LP Notion Working Layer | 0.1.0 |
| Agent OS Codespaces Profile | 0.1.0 |
| Execution Checkpoint Contract | 0.1.0 |

**Dashboard Migration Verification**
(`08_Tooling/dashboard-migration-verification/`) is a verification-only toolkit
for dashboard registry examples, placeholder snapshots, dependency graphs,
validation results, and reports. It authorizes no live Notion, Workspace,
sharing, source-of-truth, or production write. Packaging was completed by D2
(Issue #123).

**Workspace Automation Builder Tooling**
(`08_Tooling/workspace-automation-builder/`) includes an Apps Script safety
bridge, offline tests, sync safety docs, sanitized fixtures, JSON schemas, and a
local-only validator. It authorizes no live Workspace, Notion, trigger, sharing,
or production write.

**Workflow Scheduler**, **Agent Memory & Context Budget Manager**,
**IA4D-to-Scheduler Handoff Contract**, and **Agent OS Execution Service** have
extended descriptions in `04_Registry/module-version-map-details.md`. Workflow
Scheduler is `0.9.1`; Agent OS Execution Service is `0.5.0`.

**Artifact-First Response Standard**
(`01_Shared_Standards/instructional-design/artifact-first-response-standard.md`,
Issue #821) requires classroom-material responses to lead with the requested
artifact, preview, or content specification while preserving existing gates,
ownership, and stop conditions.

**Teacher Decision Studio Standard**
(`01_Shared_Standards/instructional-design/teacher-decision-studio-standard.md`
plus `teacher-decision-studio-previews-standard.md`, Issues #823 and #824)
defines table-first rubric consultation, format comparison, explanation-risk
analysis, and in-chat/PDF previews. It recommends without auto-approving and
never writes a governed field without explicit teacher confirmation.

**LP Pacing Handoff Contract**
(`01_Shared_Standards/instructional-design/lp-pacing-handoff-contract.md`,
`lp-pacing-handoff-adaptation.md`, `lp-pacing-handoff-cases.md`, and
`04_Registry/lp-pacing-handoff-contract.yaml`, Issue #648) defines a
provider-neutral pacing packet, independent authority dimensions, diagnosis,
and ordered adaptation hierarchy. It authorizes no runtime evaluator, OCR,
classroom data, external write, or gate advancement.

**LP Reason Code Catalog**
(`01_Shared_Standards/instructional-design/lp-reason-code-catalog.md` and
`04_Registry/lp-reason-code-catalog.yaml`, Issue #711) owns the finite `lp-*`
semantic catalog and producer/consumer ownership map. Generic parsing, bounds,
version, serialization, and authority mechanics remain with LP9, LP12, and CW5A.

**LP Notion Working Layer**
(`01_Shared_Standards/notion/lp-notion-working-layer-standard.md` and
`04_Registry/lp-notion-working-layer-change-request.yaml`, Issue #652) defines
the bounded working-layer design and exact-target Change Request. The request is
proposed, not authorized; six unresolved decisions block live change.

**Execution Checkpoint Contract**
(`scripts/agent_os_execution_checkpoint/`, Issue #895; design approved in
Issue #858) is the pure-local checkpoint record, content-addressed append-only
store, and resume planner; every authority field remains false.

Reconciliation notes are retained in
`04_Registry/module-version-map-details.md`.
