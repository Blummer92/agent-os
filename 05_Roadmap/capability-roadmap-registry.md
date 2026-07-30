# Agent OS Capability Roadmap Registry

## Purpose

This registry provides a capability-level view of Agent OS without replacing GitHub issues, pull requests, or detailed roadmap documents.

GitHub remains the canonical source of truth. This registry is a navigation and reporting layer only. It does not authorize implementation, merge, issue closure, external writes, production changes, or governed-field mutation.

## Maturity Stages

| Stage | Meaning |
|---|---|
| `concept` | The need is identified, but no canonical roadmap or contract exists. |
| `planned` | A canonical roadmap or contract exists with ownership and boundaries. |
| `building` | One or more bounded implementation issues are active. |
| `integrating` | Core components exist and cross-contract or end-to-end validation is active. |
| `pilot-ready` | A bounded real-world or shadow-mode pilot can run with explicit authorization. |
| `operational` | The capability is repeatable, governed, validated, and supported. |
| `paused` | Work is intentionally deferred with a recorded reason. |

## Capability Registry

| ID | Capability | Purpose | Primary Owner | Canonical Roadmap or Parent | Stage | Current Evidence | Primary Blocker or Next Gate |
|---|---|---|---|---|---|---|---|
| `CAP-CORE` | Agent OS Core Platform | Govern agents, standards, registries, validation, navigation, and controlled execution. | ChatGPT Orchestrator / Integration Manager | `05_Roadmap/implementation-roadmap.md` | `integrating` | Governance, overlays, registries, validation lanes, and safe implementation controls exist. | Reconcile older Phase 1 planning with current capability-level work and exact validation evidence. |
| `CAP-AUTO` | Autonomous GitHub Development | Produce bounded candidate packets, plans, dependency evidence, validation plans, and authorized implementation handoffs. | Agent Orchestrator / GitHub Service Agent | Issue #749 | `building` | Readiness evidence and canonical dependency identity evidence exist. | Complete the node, graph, planning, and handoff coordinator beginning with #751. |
| `CAP-CURR` | Curriculum Intelligence Platform | Route Unit Alignment, Teacher Modeling, and Instructional Materials through reusable governed contracts. | Agent Orchestrator | Issue #654 | `integrating` | Shared curriculum core, MaterialRequirement, ArtifactManifest, and reuse planning exist. | Complete cross-contract integration validation and downstream executable pipeline work. |
| `CAP-VIS` | Visual Asset Platform | Discover, validate, review, reuse, and safely route classroom images, icons, diagrams, screenshots, and exemplars. | Integration Manager / Instructional Materials Coach | Issue #785 | `building` | Visual-asset safety contract, reconciliation planner, Notion adapter lane, ArtifactManifest, and reuse planner exist. | Ratify the Visual Asset Library projection bridge and complete bounded read-only integration. |
| `CAP-PROD` | Classroom Production Pipeline | Generate governed Slides, Docs, worksheets, handouts, and related classroom artifacts into approved Drive folders. | Instructional Materials Coach | `05_Roadmap/implementation-roadmap.md` M3 and Issue #654 | `building` | Destination rules, material contracts, and generation ownership are defined. | Prove one current end-to-end classroom artifact path with exact validation and approved destination evidence. |
| `CAP-PLAN` | Teacher Planning Workspace | Use Notion as the teacher-facing layer for readiness, lesson candidates, review queues, and working knowledge. | Integration Manager / Unit Alignment Agent | Issue #654 | `building` | Notion destination and read-only boundaries are governed; several adapters and handoffs exist. | Consolidate teacher-facing projections without creating a competing source of truth or unauthorized write path. |
| `CAP-GWS` | Google Workspace Integration | Provide governed Drive, Docs, Slides, Sheets, Calendar, and related integration boundaries. | Google Workspace Automation Engineer / Integration Manager | `05_Roadmap/implementation-roadmap.md` M2-M3 | `building` | Read-only connector and Drive-destination patterns exist across multiple lanes. | Reconcile connector contracts and prove bounded end-to-end integrations without credential or permission drift. |
| `CAP-QA` | Quality Assurance Platform | Validate contracts, repository state, classroom readiness, accessibility, privacy, rights, and exact-head evidence. | QA / Test Agent | Issue #330 and repository validation standards | `integrating` | Aggregate validation, focused tests, acceptance reports, and domain validators exist. | Close remaining exact-head, connected-evidence, and post-merge evidence gaps. |
| `CAP-TA` | Teacher AI Assistant | Provide teacher-facing planning, modeling, differentiation, feedback, and communication support. | Agent Orchestrator | Issue #654 | `planned` | Canonical teaching agents and instructional standards exist. | Define one bounded teacher-facing workflow instead of broad ungoverned features. |
| `CAP-AN` | Analytics and Improvement | Produce privacy-safe usage, quality, pacing, and improvement evidence without automated instructional decisions. | Modeling & Dashboard Governance Agent | Relevant analytics and learning-pipeline roadmap issues | `planned` | Dashboard governance and reporting contracts exist. | Identify one canonical parent roadmap and define privacy-safe evidence boundaries. |

## Cross-Capability Dependencies

```text
CAP-CORE
  +--> CAP-AUTO
  +--> CAP-QA
  +--> CAP-GWS

CAP-CURR
  +--> CAP-VIS
  +--> CAP-PROD
  +--> CAP-PLAN
  +--> CAP-TA

CAP-GWS
  +--> CAP-VIS
  +--> CAP-PROD
  +--> CAP-PLAN

CAP-QA
  +--> all implementation and pilot-ready transitions

CAP-AN
  +--> consumes approved evidence from CAP-CURR, CAP-PROD, and CAP-PLAN
```

## Capability Review Record

Each capability review should report:

- capability ID and maturity stage;
- canonical roadmap or parent issue;
- completed evidence;
- active issues and draft pull requests;
- current blockers;
- next highest-value gate;
- dependencies and conflicts;
- files changed;
- tests run;
- docs updated;
- unresolved blockers;
- handoff recommendations;
- remaining risks.

## Update Policy

Update this registry only when:

1. a canonical roadmap or parent issue changes;
2. a maturity-stage transition has direct evidence;
3. ownership changes through governance;
4. a capability is added, merged, split, paused, or retired;
5. a primary blocker or next gate materially changes.

Routine child-issue activity does not require an immediate registry update unless it changes the capability-level state.
