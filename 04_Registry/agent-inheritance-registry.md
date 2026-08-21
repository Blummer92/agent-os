# Agent Inheritance Registry

Every registered agent overlay inherits the universal baseline from
`02_Agent_Overlays/_common-overlay-rules.md`: `Global Engineering`,
`Read-Only Default`, and `Source-of-Truth Checks`. The two universal safety
modules are inherited through that common baseline and are not repeated in
individual agent rows.

| Agent | Inherits | Overlay |
|---|---|---|
| ChatGPT Orchestrator | Global Engineering | chatgpt-orchestrator |
| GitHub Service Agent | Global Engineering, Python Standards | github-service-agent |
| Google Workspace Automation Engineer | Global Engineering, Google Workspace Standards, Notion Standards | google-workspace-automation-engineer |
| Modeling & Dashboard Governance Agent | Global Engineering, Dashboard Governance, Notion Standards | modeling-dashboard-governance-agent |
| Integration Manager | Global Engineering, Google Workspace Standards, Notion Standards | integration-manager |
| QA / Test Agent | Global Engineering, QA/Test Standards | qa-test-agent |
| Agent Orchestrator | Global Engineering, Instructional Design Standards | agent-orchestrator |
| Unit Alignment Agent | Global Engineering, Instructional Design Standards, Notion Standards | unit-alignment-agent |
| Teacher Modeling Coach | Global Engineering, Instructional Design Standards | teacher-modeling-coach |
| Instructional Materials Coach | Global Engineering, Google Workspace Standards, Python Standards, Instructional Design Standards | instructional-materials-coach |

## Repository Implementation Ownership

The GitHub Service Agent is the single canonical owner for ordinary Agent OS
repository implementation, regardless of programming language or subsystem.
Language and framework standards guide implementation; they do not create
additional executable agents. QA / Test Agent retains independent validation
evidence ownership, Integration Manager retains cross-system architecture and
routing ownership, and external-system specialists retain their domain and write
authorization boundaries.

## Legacy Alias Resolution

Legacy agent names and historical workflow labels are resolved using
`04_Registry/legacy-agent-alias-registry.md`.

Aliases never create new agents.

Aliases always resolve to an existing canonical registered agent.

## Routed Combinations

| Workflow | Canonical Owner | Overlays |
|---|---|---|
| ChatGPT request triage | ChatGPT Orchestrator | ChatGPT Orchestrator; selected registered owner |
| GitHub repository implementation and write | GitHub Service Agent | GitHub Service Agent; applicable language/domain standards; GitHub Change Request |
| Navigation Registry governance and lookup routing | Integration Manager | Integration Manager; Navigation Registry Standard |
| Dashboard sync, default cross-system route | Integration Manager | Dashboard Builder Overlay; Apps Script Sync Test Overlay |
| Dashboard sync, governance-heavy route | Modeling & Dashboard Governance Agent | Dashboard Builder Overlay |
| Dashboard sync, Workspace-domain requirements | Google Workspace Automation Engineer | Workspace Implementation Overlay; Apps Script Sync Test Overlay |
| Dashboard sync, repository implementation | GitHub Service Agent | applicable Workspace requirements; GitHub Service Agent |
| Dashboard sync, validation-heavy route | QA / Test Agent | Apps Script Sync Test Overlay |
| Curriculum design, Unit Alignment -> Teacher Modeling -> Instructional Materials pipeline | Agent Orchestrator -> selected pipeline owner | Agent Orchestrator; Instructional Design Standards |
