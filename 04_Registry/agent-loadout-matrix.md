# Agent Loadout Matrix

Routing aid only. It does not grant permission or override governance, ownership,
write authorization, or system-of-record rules.

All agents inherit `02_Agent_Overlays/_common-overlay-rules.md`, including Global
Engineering, Read-Only Default, and Source-of-Truth Checks. Risk tiers come from
`04_Registry/agent-risk-tiers.md`; intake comes from
`03_Templates/prompts/agent-intake-form.md`.

| Agent | Overlay | Additional inherited standards | Default tier/write mode | Primary work | Evidence and escalation |
|---|---|---|---|---|---|
| ChatGPT Orchestrator | `chatgpt-orchestrator` | Baseline only | Tier 0, read-only | Request triage and owner routing | Escalate repository or external writes to the registered owner |
| GitHub Service Agent | `github-service-agent` | Baseline only | Tier 2 for approved repository writes | Issues, branches, commits, PRs, repository handoffs | Exact target, approval, tests, final-head evidence; no external-system writes |
| Google Workspace Automation Engineer | `google-workspace-automation-engineer` | Python, Google Workspace, Notion | Tier 1 local; Tier 2/3 external | Python tooling and approved workspace implementation | Full intake for external writes; stop on unknown schema, owner, or credentials |
| Modeling & Dashboard Governance Agent | `modeling-dashboard-governance-agent` | Dashboard Governance, Notion | Tier 0 review; Tier 2/3 governed changes | Dashboard model and field governance | Owner approval for governed fields; no implementation by implication |
| Integration Manager | `integration-manager` | Google Workspace, Notion | Tier 0 routing; Tier 2 governed coordination | Cross-system routing, Navigation Registry, capability policy | Verify source of truth and owners; external changes require separate approval |
| QA / Test Agent | `qa-test-agent` | QA/Test | Tier 0, read-only evidence | Acceptance, validation, release-readiness evidence | Report pass/fail and risks; evidence never authorizes merge or writes |
| Agent Orchestrator | `agent-orchestrator` | Instructional Design | Tier 0/1 planning | Curriculum pipeline routing | Route production artifacts to approved Drive destinations |
| Unit Alignment Agent | `unit-alignment-agent` | Instructional Design, Notion | Tier 0/1 planning | Standards and unit alignment | Escalate live Notion or canonical curriculum changes |
| Teacher Modeling Coach | `teacher-modeling-coach` | Instructional Design | Tier 0/1 local drafting | Lesson modeling and teacher-talk coaching | Route student-facing production to Instructional Materials Coach |
| Instructional Materials Coach | `instructional-materials-coach` | Google Workspace, Python, Instructional Design | Tier 1 local; Tier 2 external copies | Slides, worksheets, and classroom artifacts | Use approved Drive folders; full intake before external creation or sharing |

## Governed Routing Overlays

| Overlay | Use with | Boundary |
|---|---|---|
| Python Development Overlay | Google Workspace Automation Engineer or approved local tooling owner | Local code by default; repository writes through GitHub Service Agent |
| Dashboard Builder Overlay | Integration Manager or Modeling & Dashboard Governance Agent | Draft locally; governed-field changes require owner approval |
| Workspace Implementation Overlay | Google Workspace Automation Engineer | External implementation only after full intake and target approval |
| Apps Script Sync Test Overlay | Integration Manager or QA / Test Agent | Validation evidence; no production mutation by default |
| GitHub Change Request | Any non-GitHub agent | Handoff to GitHub Service Agent; never a direct repository write |

## Required Registries And Templates

Always consult `04_Registry/agent-inheritance-registry.md` and
`04_Registry/responsibility-matrix.md`. Use the lightweight intake for Tier 0 and
Tier 1 work. Use Full Intake plus `03_Templates/reports/live-readiness-checklist.md`
for Tier 2, Tier 3, governed, production, external-write, permission, sharing,
source-of-truth, sensitive-data, or irreversible work.

## Stop Conditions

Stop for human decision when the owner, overlay, source of truth, risk tier, target,
write surface, approval, evidence requirement, or output destination is unclear.