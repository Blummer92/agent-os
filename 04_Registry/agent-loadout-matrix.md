# Agent Loadout Matrix

Routing aid only. It does not grant permission or override governance, ownership,
write authorization, or system-of-record rules.

All canonical agents inherit `02_Agent_Overlays/_common-overlay-rules.md`. Shared
technical standards and helper overlays can refine a canonical job but never
create another executable agent.

| Agent | Overlay | Additional inherited standards | Default tier/write mode | Primary work | Evidence and escalation |
|---|---|---|---|---|---|
| ChatGPT Orchestrator | `chatgpt-orchestrator` | Navigation, Google Workspace, reusable-capability, source-of-truth standards as applicable | Tier 0, read-only routing | Request triage, cross-system/source-of-truth routing, capability selection | Escalate repository implementation to GitHub Service Agent; external operations require exact authorization |
| GitHub Service Agent | `github-service-agent` | Python and applicable language/domain/provider standards | Tier 1/2 for authorized repository work | All repository engineering, branches, commits, PRs | Exact target, authorization, tests, final-head evidence; no blanket external-system writes |
| Modeling & Dashboard Governance Agent | `modeling-dashboard-governance-agent` | Dashboard Governance, Notion | Tier 0 review; Tier 2/3 governed changes | Dashboard model and field governance | Owner approval for governed fields; repository implementation routes to GitHub Service Agent |
| QA / Test Agent | `qa-test-agent` | QA/Test | Tier 0, read-only evidence | Acceptance, regression, validation, release-readiness evidence | Report pass/fail/manual-review and risks; evidence never authorizes merge or writes |
| Agent Orchestrator | `agent-orchestrator` | Instructional Design | Tier 0/1 planning | Curriculum pipeline routing | Route production artifacts to approved Drive destinations |
| Unit Alignment Agent | `unit-alignment-agent` | Instructional Design, Notion | Tier 0/1 planning | Standards and unit alignment | Escalate live Notion or canonical curriculum changes |
| Teacher Modeling Coach | `teacher-modeling-coach` | Instructional Design | Tier 0/1 local drafting | Lesson modeling and teacher-talk coaching | Route student-facing production to Instructional Materials Coach |
| Instructional Materials Coach | `instructional-materials-coach` | Google Workspace, Python, Instructional Design | Tier 1 local; Tier 2 external copies | Slides, worksheets, and classroom artifacts | Use approved Drive folders; full intake before external creation or sharing |

## Governed Routing Overlays And Capabilities

| Overlay or capability | Use with | Boundary |
|---|---|---|
| Python Development Overlay | GitHub Service Agent | Legacy compatibility only; current Python rules live under `01_Shared_Standards/python/` |
| Google Workspace Standards | ChatGPT Orchestrator; GitHub Service Agent | Orchestrator classifies external-operation intent; GitHub Service Agent owns repository implementation; standards never grant writes |
| Workspace Implementation Overlay | ChatGPT Orchestrator; GitHub Service Agent | Capability guidance only; external mutation requires separate exact-target authorization |
| Dashboard Builder Overlay | ChatGPT Orchestrator; Modeling & Dashboard Governance Agent | Draft locally; governed-field changes require owner approval; repository code routes to GitHub Service Agent |
| Apps Script Sync Test Overlay | QA / Test Agent; GitHub Service Agent | QA owns independent evidence; GitHub owns repository test implementation; no production mutation by default |
| GitHub Change Request | Any non-GitHub agent or routed capability | Handoff to GitHub Service Agent; never a direct repository write |

`Integration Manager` and `Google Workspace Automation Engineer` are retired
canonical names and must not appear as loadout agents. Resolve them through the
legacy alias registry.

## Required Registries And Templates

Always consult `04_Registry/agent-inheritance-registry.md` and
`04_Registry/responsibility-matrix.md`. Use Lightweight Intake for Tier 0/1
read-only/local-only work. Use Full Intake plus live-readiness evidence for Tier
2/3, governed, production, external-write, permission, sharing, source-of-truth,
sensitive-data, or irreversible work.

## Stop Conditions

Stop for human decision when the canonical job owner, shared standard, source of
truth, risk tier, target, operation, write surface, approval, evidence
requirement, or output destination is unclear.
