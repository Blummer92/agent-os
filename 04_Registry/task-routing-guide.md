# Task Routing Guide

Use this guide to select a primary role and safe workflow. Authority remains in
canonical governance, ownership, registry, and source-of-truth records.

| Workflow | Primary role | Support or overlay | Tier and intake | Source and destination | Stop or escalate when |
|---|---|---|---|---|---|
| Read-only review | QA / Test Agent | Relevant registered owner | Tier 0, Lightweight | Read canonical source; report evidence | Access, source identity, or scope is unclear |
| Local planning or specification | ChatGPT Orchestrator | Selected owner | Tier 0/1, Lightweight | Local draft or approved planning surface | Draft is about to be published or copied externally |
| Local Python or tooling work | Google Workspace Automation Engineer | Python Development Overlay | Tier 1, Lightweight | Local files; GitHub changes via handoff | Repository or external write is needed |
| Package or test work | QA / Test Agent | Python Development Overlay; package owner | Tier 1 local; Tier 2 repository write | Local fixtures, then GitHub Service Agent | Test surface, owner, or allowed files are unknown |
| Dashboard draft | Integration Manager | Dashboard Builder Overlay | Tier 1, Lightweight | Local dashboard map or specification | Governed fields or live systems are involved |
| Governed dashboard change | Modeling & Dashboard Governance Agent | Dashboard Builder Overlay; Integration Manager | Tier 2/3, Full plus Live Readiness | Authoritative dashboard source | Field owner, approval, rollback, or target is missing |
| Google Workspace automation | Google Workspace Automation Engineer | Workspace Implementation Overlay | Tier 2/3, Full plus Live Readiness | Approved Workspace target | IDs, schema, owner, permissions, or approval are unclear |
| Apps Script validation | QA / Test Agent | Apps Script Sync Test Overlay | Tier 0/1 for isolated tests; Tier 2 for live test | Fixture first; approved script target when authorized | Production execution or mutation is implied |
| Workspace implementation | Google Workspace Automation Engineer | Integration Manager | Tier 2/3, Full plus Live Readiness | Approved Drive, Docs, Sheets, Slides, or Apps Script target | Sharing, production, credentials, or rollback is unresolved |
| QA or release readiness | QA / Test Agent | GitHub Service Agent or system owner | Tier 0 evidence | Test results and final report | Evidence is stale, incomplete, or bound to the wrong SHA |
| Slides or worksheets | Instructional Materials Coach | Python Development Overlay | Tier 1 local; Tier 2 approved external copy | Approved Google Drive classroom folder | Destination, student-data boundary, or sharing is unclear |
| Standards, overlay, governance, or registry change | Integration Manager | GitHub Service Agent; QA / Test Agent | Tier 2, Full plus Live Readiness | GitHub `main` through reviewed PR | Ownership, compatibility, tests, or migration impact is unclear |
| Ambiguous write request | Integration Manager | ChatGPT Orchestrator; target owner | Manual review | No write destination until resolved | Any owner, target, permission, or source-of-truth ambiguity remains |
| GitHub issue or PR management | GitHub Service Agent | QA / Test Agent | Tier 2, Full intake for writes | GitHub repository | Authorization, exact item, or mutation scope is unclear |

## Routing Sequence

1. Identify the canonical source of truth and target owner.
2. Select the primary role from the responsibility matrix.
3. Load the registered overlay and inherited standards.
4. Classify the highest applicable risk tier.
5. Use Lightweight Intake only for Tier 0 or Tier 1 read-only/local-only work.
6. Use Full Intake and Live Readiness for Tier 2, Tier 3, governed, production,
   external-write, permission, sharing, source-of-truth, sensitive-data, or
   irreversible work.
7. Send repository writes through the GitHub Service Agent.
8. Record tests, evidence, blockers, handoffs, and remaining risks.

## Destination Rules

- Agent OS governance, standards, overlays, registries, templates, tests, and release
  notes default to GitHub.
- Teacher planning and working knowledge default to Notion or a Notion handoff.
- Student-facing Slides, Docs, worksheets, and classroom materials default to approved
  Google Drive folders.
- Classroom artifacts require explicit approval before GitHub storage.

## Fail-Closed Rules

Validation, capability, readiness, labels, templates, and routing recommendations do
not grant authorization. Missing or conflicting ownership, target, source, approval,
write-surface, or provenance evidence routes to human decision.