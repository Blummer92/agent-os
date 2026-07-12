# Agent Inheritance Registry

| Agent | Inherits | Overlay |
|---|---|---|
| Google Workspace Automation Engineer | Global, Python, Workspace, Notion | google-workspace-automation-engineer |
| Modeling & Dashboard Governance Agent | Global, Dashboard Governance, Notion | modeling-dashboard-governance-agent |
| Integration Manager | Global, Workspace, Notion | integration-manager |
| QA / Test Agent | Global, QA/Test | qa-test-agent |
| Unit Alignment Agent | Global, Instructional Design | unit-alignment-agent |
| Teacher Modeling Coach | Global, Instructional Design | teacher-modeling-coach |
| Instructional Materials Coach | Global, Workspace, Python, Instructional Design | instructional-materials-coach |

## Routed Combinations

| Workflow | Canonical Owner | Overlays |
|---|---|---|
| Dashboard sync, default cross-system route | Integration Manager | Dashboard Builder Overlay; Apps Script Sync Test Overlay |
| Dashboard sync, governance-heavy route | Modeling & Dashboard Governance Agent | Dashboard Builder Overlay |
| Dashboard sync, implementation-heavy route | Google Workspace Automation Engineer | Workspace Implementation Overlay; Apps Script Sync Test Overlay |
| Dashboard sync, validation-heavy route | QA / Test Agent | Apps Script Sync Test Overlay |
| Curriculum design, Unit Alignment → Teacher Modeling → Instructional Materials pipeline | Unit Alignment Agent → Teacher Modeling Coach → Instructional Materials Coach | Instructional Design Standards |