# Task Routing Guide

Use this guide to select a canonical role and safe workflow. Technical subjects
are standards/capabilities unless the canonical agent registry explicitly says
otherwise. Authority remains in governance, source-of-truth, and write-
authorization records.

| Workflow | Primary role | Support or overlay | Tier and intake | Source and destination | Stop or escalate when |
|---|---|---|---|---|---|
| Read-only review | QA / Test Agent | Relevant registered owner | Tier 0, Lightweight | Read canonical source; report evidence | Access, source identity, or scope is unclear |
| Local planning or specification | ChatGPT Orchestrator | Selected owner | Tier 0/1, Lightweight | Local draft or approved planning surface | Draft is about to be published or copied externally |
| Local Python or repository tooling work | GitHub Service Agent | Python Standards | Tier 1, Lightweight | Local/repository engineering; GitHub writes under authorized lane | Repository scope or write authorization is unclear |
| Package, fixture, or implementation-test work | GitHub Service Agent | QA / Test Agent; Python Standards | Tier 1 local; Tier 1/2 repository write | Local fixtures, then governed GitHub path | Test surface, owner, or allowed files are unknown |
| Cross-system/source-of-truth routing | ChatGPT Orchestrator | Navigation Registry Standard; Source-of-Truth Checks | Tier 0/1, Lightweight | Routing/spec evidence only | Source, owner, or authoritative system conflicts |
| Dashboard draft | ChatGPT Orchestrator | Dashboard Builder Overlay | Tier 1, Lightweight | Local dashboard map or specification | Governed fields or live systems are involved |
| Governed dashboard change | Modeling & Dashboard Governance Agent | Dashboard Builder Overlay; ChatGPT Orchestrator | Tier 2/3, Full plus Live Readiness | Authoritative dashboard source | Field owner, approval, rollback, or target is missing |
| Google Workspace automation design or external-operation routing | ChatGPT Orchestrator | Google Workspace Standards; Workspace Implementation Overlay | Tier 2/3, Full plus Live Readiness | Approved Workspace target or dry-run plan | IDs, schema, owner, permissions, operation, or approval are unclear |
| Workspace repository implementation | GitHub Service Agent | Google Workspace Standards; Workspace Implementation Overlay | Tier 1/2, Full plus Live Readiness | GitHub repository | External mutation, credentials, sharing, production, or rollback enters scope |
| Apps Script repository implementation | GitHub Service Agent | Google Workspace Standards; Apps Script Sync Test Overlay | Tier 1/2, Full plus Live Readiness | GitHub repository | Deployment, trigger creation, credentials, or live mutation is implied |
| Apps Script or Workspace validation | QA / Test Agent | Apps Script Sync Test Overlay | Tier 0/1 isolated; Tier 2 live test | Fixture first; approved target only when separately authorized | Production execution or mutation is implied |
| QA or release readiness | QA / Test Agent | GitHub Service Agent | Tier 0 evidence | Test results and final report | Evidence is stale, incomplete, or bound to the wrong SHA |
| Slides or worksheets | Instructional Materials Coach | Python Standards | Tier 1 local; Tier 2 approved external copy | Approved Google Drive classroom folder | Destination, student-data boundary, or sharing is unclear |
| Standards, overlay, governance, or registry repository change | GitHub Service Agent | ChatGPT Orchestrator; QA / Test Agent | Tier 2, Full plus Live Readiness | GitHub `main` through reviewed PR | Ownership, compatibility, tests, or migration impact is unclear |
| Ambiguous write request | ChatGPT Orchestrator | target owner | Manual review | No write destination until resolved | Any owner, target, permission, operation, or source-of-truth ambiguity remains |
| GitHub issue or PR management | GitHub Service Agent | QA / Test Agent | Tier 2, Full intake for writes | GitHub repository | Authorization, exact item, or mutation scope is unclear |

## Routing Sequence

1. Identify the canonical source of truth and exact target.
2. Resolve legacy agent names through `legacy-agent-alias-registry.md`.
3. Select a canonical agent only for a repeatable job; otherwise select the
   relevant shared capability/standard.
4. Route all repository implementation to GitHub Service Agent.
5. Route independent validation evidence to QA / Test Agent.
6. Route cross-system, source-of-truth, capability, and external-operation
   classification through ChatGPT Orchestrator plus the governing standards.
7. Use Lightweight Intake only for Tier 0 or Tier 1 read-only/local-only work.
8. Use Full Intake and Live Readiness for Tier 2, Tier 3, governed, production,
   external-write, permission, sharing, source-of-truth, sensitive-data, or
   irreversible work.
9. Record tests, evidence, blockers, handoffs, and remaining risks.

## Destination Rules

- Agent OS governance, standards, overlays, registries, templates, tests, and
  release notes default to GitHub.
- Teacher planning and working knowledge default to Notion or a Notion handoff.
- Student-facing Slides, Docs, worksheets, and classroom materials default to
  approved Google Drive folders.
- Classroom artifacts require explicit approval before GitHub storage.

## Fail-Closed Rules

Validation, capability, readiness, labels, templates, routing recommendations,
and legacy aliases never grant authorization. Missing or conflicting ownership,
target, source, approval, operation, write-surface, or provenance evidence routes
to human decision. Repository implementation authority never implies Workspace,
Notion, Drive, production, credential, sharing, or permission authority.
