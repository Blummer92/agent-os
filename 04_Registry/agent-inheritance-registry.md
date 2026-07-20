# Agent Inheritance Registry

| Agent | Inherits | Overlay |
|---|---|---|
| ChatGPT Orchestrator | Global Engineering, Source-of-Truth Checks, Read-Only Default | chatgpt-orchestrator |
| GitHub Service Agent | Global Engineering, Source-of-Truth Checks, Read-Only Default | github-service-agent |
| Google Workspace Automation Engineer | Global Engineering, Python Standards, Google Workspace Standards, Notion Standards | google-workspace-automation-engineer |
| Modeling & Dashboard Governance Agent | Global Engineering, Dashboard Governance, Notion Standards | modeling-dashboard-governance-agent |
| Integration Manager | Global Engineering, Google Workspace Standards, Notion Standards | integration-manager |
| QA / Test Agent | Global Engineering, QA/Test Standards | qa-test-agent |
| Agent Orchestrator | Global Engineering, Instructional Design Standards | agent-orchestrator |
| Unit Alignment Agent | Global Engineering, Instructional Design Standards, Notion Standards | unit-alignment-agent |
| Teacher Modeling Coach | Global Engineering, Instructional Design Standards | teacher-modeling-coach |
| Instructional Materials Coach | Global Engineering, Google Workspace Standards, Python Standards, Instructional Design Standards | instructional-materials-coach |

## Legacy Alias Resolution

Legacy agent names and historical workflow labels are resolved using
`04_Registry/legacy-agent-alias-registry.md`.

Aliases never create new agents.

Aliases always resolve to an existing canonical registered agent.

## Routed Combinations

| Workflow | Canonical Owner | Overlays |
|---|---|---|
| ChatGPT request triage | ChatGPT Orchestrator | ChatGPT Orchestrator; selected registered owner |
| GitHub repository write | GitHub Service Agent | GitHub Service Agent; GitHub Change Request |
| Navigation Registry governance and lookup routing | Integration Manager | Integration Manager; Navigation Registry Standard |
| Dashboard sync, default cross-system route | Integration Manager | Dashboard Builder Overlay; Apps Script Sync Test Overlay |
| Dashboard sync, governance-heavy route | Modeling & Dashboard Governance Agent | Dashboard Builder Overlay |
| Dashboard sync, implementation-heavy route | Google Workspace Automation Engineer | Workspace Implementation Overlay; Apps Script Sync Test Overlay |
| Dashboard sync, validation-heavy route | QA / Test Agent | Apps Script Sync Test Overlay |
| Curriculum design, Unit Alignment -> Teacher Modeling -> Instructional Materials pipeline | Agent Orchestrator -> selected pipeline owner | Agent Orchestrator; Instructional Design Standards |
