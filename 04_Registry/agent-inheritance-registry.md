# Agent Inheritance Registry

Every registered agent overlay inherits the universal baseline from
`02_Agent_Overlays/_common-overlay-rules.md`: `Global Engineering`,
`Read-Only Default`, and `Source-of-Truth Checks`. Shared technical standards
supply language, platform, integration, and provider constraints without creating
additional executable agents.

| Agent | Inherits | Overlay |
|---|---|---|
| ChatGPT Orchestrator | Global Engineering | chatgpt-orchestrator |
| GitHub Service Agent | Global Engineering, Python Standards | github-service-agent |
| Modeling & Dashboard Governance Agent | Global Engineering, Dashboard Governance, Notion Standards | modeling-dashboard-governance-agent |
| QA / Test Agent | Global Engineering, QA/Test Standards | qa-test-agent |
| Agent Orchestrator | Global Engineering, Instructional Design Standards | agent-orchestrator |
| Unit Alignment Agent | Global Engineering, Instructional Design Standards, Notion Standards | unit-alignment-agent |
| Teacher Modeling Coach | Global Engineering, Instructional Design Standards | teacher-modeling-coach |
| Instructional Materials Coach | Global Engineering, Google Workspace Standards, Python Standards, Instructional Design Standards | instructional-materials-coach |

## Technical Execution Architecture

Agent OS has two canonical technical execution roles:

1. **GitHub Service Agent** — the single canonical owner for authorized repository
   implementation and GitHub delivery, regardless of programming language,
   framework, provider, or integration domain.
2. **QA / Test Agent** — independent technical validation and evidence.

Google Workspace, Apps Script, Python, integration architecture, Cloud Build,
frontend technologies, and similar technical subjects are capabilities, shared
standards, overlays, or provider contracts. They do not create executable agents.

`Integration Manager` and `Google Workspace Automation Engineer` are retired
canonical agent names. Historical input resolves through
`04_Registry/legacy-agent-alias-registry.md`; their retained overlay files are
compatibility guidance only and are not executable registrations.

## Legacy Alias Resolution

Legacy agent names and historical workflow labels are resolved using
`04_Registry/legacy-agent-alias-registry.md`.

Aliases never create new agents. They always resolve to a canonical registered
agent before execution.

## Routed Combinations

| Workflow | Canonical Owner | Overlays |
|---|---|---|
| ChatGPT request triage | ChatGPT Orchestrator | ChatGPT Orchestrator; selected registered owner or shared capability standard |
| GitHub repository implementation and write | GitHub Service Agent | GitHub Service Agent; applicable language/domain standards; GitHub Change Request |
| Cross-system, source-of-truth, Navigation Registry, and reusable-capability routing | ChatGPT Orchestrator | Navigation Registry Standard; Reusable Capability Registry Standard; applicable system standards |
| Workspace automation requirements and authorized external-operation routing | ChatGPT Orchestrator | Google Workspace Standards; Workspace Implementation Overlay |
| Workspace or Apps Script repository implementation | GitHub Service Agent | Google Workspace Standards; Apps Script standards; Workspace Implementation Overlay |
| Dashboard sync routing | ChatGPT Orchestrator | Dashboard Builder Overlay; Apps Script Sync Test Overlay |
| Dashboard sync governance | Modeling & Dashboard Governance Agent | Dashboard Builder Overlay |
| Dashboard sync repository implementation | GitHub Service Agent | Google Workspace Standards; Workspace Implementation Overlay |
| Dashboard sync validation evidence | QA / Test Agent | Apps Script Sync Test Overlay |
| Curriculum design, Unit Alignment -> Teacher Modeling -> Instructional Materials pipeline | Agent Orchestrator -> selected pipeline owner | Agent Orchestrator; Instructional Design Standards |
