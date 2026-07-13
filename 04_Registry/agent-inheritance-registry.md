# Agent Inheritance Registry

| Agent | Inherits | Overlay |
|---|---|---|
| ChatGPT Orchestrator | Global, Source-of-Truth, Read-Only Default | chatgpt-orchestrator |
| GitHub Service Agent | Global, Source-of-Truth, Read-Only Default, Testing/Release | github-service-agent |
| Google Workspace Automation Engineer | Global, Python, Workspace, Notion | google-workspace-automation-engineer |
| Modeling & Dashboard Governance Agent | Global, Dashboard Governance, Notion | modeling-dashboard-governance-agent |
| Integration Manager | Global, Workspace, Notion | integration-manager |
| QA / Test Agent | Global, QA/Test | qa-test-agent |
| Agent Orchestrator | Global, Instructional Design | agent-orchestrator |
| Unit Alignment Agent | Global, Instructional Design, Notion | unit-alignment-agent |
| Teacher Modeling Coach | Global, Instructional Design | teacher-modeling-coach |
| Instructional Materials Coach | Global, Workspace, Python, Instructional Design | instructional-materials-coach |

## Routed Combinations

| Workflow | Canonical Owner | Overlays |
|---|---|---|
| ChatGPT request triage | ChatGPT Orchestrator | ChatGPT Orchestrator; selected registered owner |
| GitHub repository write | GitHub Service Agent | GitHub Service Agent; GitHub Change Request |
| Dashboard sync, default cross-system route | Integration Manager | Dashboard Builder Overlay; Apps Script Sync Test Overlay |
| Dashboard sync, governance-heavy route | Modeling & Dashboard Governance Agent | Dashboard Builder Overlay |
| Dashboard sync, implementation-heavy route | Google Workspace Automation Engineer | Workspace Implementation Overlay; Apps Script Sync Test Overlay |
| Dashboard sync, validation-heavy route | QA / Test Agent | Apps Script Sync Test Overlay |
| Curriculum design, Unit Alignment -> Teacher Modeling -> Instructional Materials pipeline | Agent Orchestrator -> selected pipeline owner | Agent Orchestrator; Instructional Design Standards |