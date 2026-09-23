# Legacy Agent Alias Registry

## Purpose

This registry maps legacy agent names, old property values, and superseded
workflow labels to current canonical Agent OS owners. Aliases are compatibility
input only; they never create executable agents or write authority.

## Source Of Truth

Canonical agents are defined only in `04_Registry/agent-inheritance-registry.md`.

## Resolution Rules

- Match legacy names case-insensitively.
- Resolve the alias to the listed canonical agent before selecting an execution owner.
- Apply the capability/standard guidance in Notes when present.
- Report alias resolution when a legacy value is used.
- Do not write legacy values back into governed source-of-truth fields without approval.
- Programming language, framework, platform, provider, or integration-domain names do not create executable agents.
- Alias resolution never grants external-system or repository write authority.

## Alias Table

| Legacy Name / Property | Canonical Agent | Current Overlay | Status | Notes |
|---|---|---|---|---|
| Integration Manager | ChatGPT Orchestrator | `chatgpt-orchestrator` | active alias | Retired canonical technical role. Use shared navigation, source-of-truth, reusable-capability, dependency, and compatibility standards for routing; repository implementation goes to GitHub Service Agent. |
| Source Reviewer | ChatGPT Orchestrator | `chatgpt-orchestrator` | active alias | Use source-of-truth and navigation standards; route validation evidence to QA / Test Agent. |
| Google Workspace Automation Engineer | GitHub Service Agent | `github-service-agent` | active alias | Retired canonical technical role. For repository engineering apply Google Workspace standards; a live Workspace mutation remains separately authorization-gated and is routed as a capability, not granted by this alias. |
| Workspace Automation Developer | GitHub Service Agent | `github-service-agent` | active alias | Repository implementation uses GitHub Service Agent plus Google Workspace standards. Live Workspace operations require separate exact-target authorization. |
| Sync Builder | GitHub Service Agent | `github-service-agent` | active alias | Repository sync implementation uses GitHub Service Agent plus applicable Workspace/Apps Script standards. |
| Python Development Overlay | GitHub Service Agent | `github-service-agent` | active alias | Legacy implementation-role name. Apply shared Python Standards; do not create a Python executable agent. |
| Python Developer | GitHub Service Agent | `github-service-agent` | active alias | Programming language alone does not select a new agent; apply shared Python Standards. |
| Unit Alignment Planner | Unit Alignment Agent | `unit-alignment-agent` | active alias | Use for unit structure, alignment evidence, readiness, learning targets, assessment alignment, and lesson-sequence coherence. |
| Modeling Coach | Teacher Modeling Coach | `teacher-modeling-coach` | active alias | Use for think-alouds, worked examples, modeling grain size, fading plans, and demonstration quality after alignment readiness is met. |
| Materials Builder | Instructional Materials Coach | `instructional-materials-coach` | active alias | Use for student-facing slides, worksheets, packets, Docs, and classroom materials once gates are ready. |
| Slide Builder | Instructional Materials Coach | `instructional-materials-coach` | active alias | Use for classroom slide deck generation and revision. |
| Worksheet Builder | Instructional Materials Coach | `instructional-materials-coach` | active alias | Use for worksheets, packets, and printable/student-facing documents. |
| Dashboard Builder | Modeling & Dashboard Governance Agent | `modeling-dashboard-governance-agent` | provisional | Use for governed dashboard schema/readiness/source-of-truth concerns; repository implementation routes to GitHub Service Agent. |
| QA Agent | QA / Test Agent | `qa-test-agent` | active alias | Use for validation, regression checks, acceptance evidence, and release review. |
| Test Agent | QA / Test Agent | `qa-test-agent` | active alias | Use for validation, regression checks, acceptance evidence, and release review. |
| GitHub Agent | GitHub Service Agent | `github-service-agent` | active alias | Use for repository implementation, writes, commits, pull requests, release notes, and GitHub source-of-truth changes. |

## Ambiguous Legacy Values

| Legacy Name / Property | Default Canonical Agent | Alternate Canonical Agent | Disambiguation Rule |
|---|---|---|---|
| Dashboard Agent | Modeling & Dashboard Governance Agent | ChatGPT Orchestrator; GitHub Service Agent | Use Modeling & Dashboard Governance Agent for governed schema/readiness; ChatGPT Orchestrator for cross-system routing; GitHub Service Agent for repository implementation. |
| Workspace Builder | ChatGPT Orchestrator | GitHub Service Agent; Instructional Materials Coach | Use ChatGPT Orchestrator to classify external-operation vs. repository vs. classroom-artifact intent; repository implementation goes to GitHub Service Agent and classroom artifacts to Instructional Materials Coach. |

## Version

0.3.0

## Changelog

- 0.3.0 retires Integration Manager and Google Workspace Automation Engineer as canonical technical agents and resolves their legacy names to retained canonical agents plus shared standards/capability routing (#1324).
- 0.2.0 resolved the legacy Python Development Overlay to GitHub Service Agent and narrowed Workspace implementation aliases (#1324).
- 0.1.1 added Workspace Automation Developer as a legacy alias.
- 0.1.0 initial legacy alias registry.
