# Legacy Agent Alias Registry

## Purpose

This registry maps legacy agent names, old Notion agent-property values, and superseded workflow labels to current canonical Agent OS owners.

Aliases do not create new agents. They only help ChatGPT Orchestrator and other routing surfaces resolve older language to registered canonical agents.

## Source Of Truth

Canonical agents remain defined in `04_Registry/agent-inheritance-registry.md`.

This file owns legacy alias resolution only.

## Resolution Rules

- Match legacy names case-insensitively.
- Resolve aliases to the listed canonical agent before selecting overlays or handoff targets.
- Report the alias resolution in routing output when a legacy value is used.
- If a legacy value is not listed here, stop and request a registry update instead of inventing an agent.
- Do not write legacy values back into governed source-of-truth fields unless explicitly approved.
- Programming-language names do not create executable agents; legacy implementation-role names resolve to the canonical repository implementation owner when listed below.

## Alias Table

| Legacy Name / Property | Canonical Agent | Current Overlay | Status | Notes |
|---|---|---|---|---|
| Source Reviewer | Integration Manager | `integration-manager` | provisional | Use for source review and source-confidence routing unless the request is governance-heavy or validation-heavy. |
| Unit Alignment Planner | Unit Alignment Agent | `unit-alignment-agent` | active alias | Use for unit structure, alignment evidence, readiness, learning targets, assessment alignment, and lesson-sequence coherence. |
| Modeling Coach | Teacher Modeling Coach | `teacher-modeling-coach` | active alias | Use for think-alouds, worked examples, modeling grain size, fading plans, and demonstration quality after alignment readiness is met. |
| Materials Builder | Instructional Materials Coach | `instructional-materials-coach` | active alias | Use for student-facing slides, worksheets, packets, Docs, and classroom materials once gates are ready. |
| Slide Builder | Instructional Materials Coach | `instructional-materials-coach` | active alias | Use for classroom slide deck generation and revision. |
| Worksheet Builder | Instructional Materials Coach | `instructional-materials-coach` | active alias | Use for worksheets, packets, and printable/student-facing documents. |
| Dashboard Builder | Modeling & Dashboard Governance Agent | `modeling-dashboard-governance-agent` | provisional | Use for dashboard schema, governed field, readiness, source-of-truth, and duplicate-prevention concerns. |
| Workspace Automation Developer | Google Workspace Automation Engineer | `google-workspace-automation-engineer` | active alias | Use for Workspace automation design and Workspace-specific implementation constraints; repository implementation routes through GitHub Service Agent. |
| Sync Builder | Google Workspace Automation Engineer | `google-workspace-automation-engineer` | provisional | Use for Workspace-domain sync requirements; repository implementation routes through GitHub Service Agent. |
| Python Development Overlay | GitHub Service Agent | `github-service-agent` | active alias | Legacy implementation-role name. Apply shared Python Standards; do not create a Python executable agent. |
| QA Agent | QA / Test Agent | `qa-test-agent` | active alias | Use for validation, regression checks, acceptance evidence, and release review. |
| Test Agent | QA / Test Agent | `qa-test-agent` | active alias | Use for validation, regression checks, acceptance evidence, and release review. |
| GitHub Agent | GitHub Service Agent | `github-service-agent` | active alias | Use for repository implementation, writes, commits, pull requests, release notes, and GitHub source-of-truth changes. |

## Ambiguous Legacy Values

Some older names may map to different canonical owners depending on the request.

| Legacy Name / Property | Default Canonical Agent | Alternate Canonical Agent | Disambiguation Rule |
|---|---|---|---|
| Source Reviewer | Integration Manager | Modeling & Dashboard Governance Agent; QA / Test Agent | Use Integration Manager for source routing, Modeling & Dashboard Governance Agent for governed schema/readiness concerns, and QA / Test Agent for validation evidence. |
| Dashboard Agent | Modeling & Dashboard Governance Agent | Integration Manager; Google Workspace Automation Engineer | Use governance owner for schema/source-of-truth risk, Integration Manager for sync routing, and Workspace Automation Engineer for Workspace-domain requirements; repository implementation remains GitHub Service Agent-owned. |
| Workspace Builder | Google Workspace Automation Engineer | Instructional Materials Coach | Use Workspace Automation Engineer for automation/domain design and external-operation constraints; use Instructional Materials Coach for classroom artifacts in Drive. Repository implementation remains GitHub Service Agent-owned. |

## Version

0.2.0

## Changelog

- 0.2.0 resolves the legacy Python Development Overlay to GitHub Service Agent and narrows Workspace implementation aliases to domain requirements rather than generic repository coding (#1324).
- 0.1.1 added Workspace Automation Developer as a legacy alias.
- 0.1.0 initial legacy alias registry.
