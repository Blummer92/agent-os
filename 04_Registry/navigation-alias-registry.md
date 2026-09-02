# Navigation Alias Registry

## Purpose

This file maps stable human-readable aliases to common Agent OS reading paths so
canonical agents and capability routes can find governed documentation without
repeated manual searches.

Aliases are lookup aids only. They do not change source-of-truth ownership, grant
write authority, replace live verification, or create executable agents.

## Validation

Every file path listed in an alias must exist. Missing paths block automatic alias
use and require Navigation Alias Registry review.

## Starter Aliases

### @governance-start

| Field | Value |
|---|---|
| Alias | `@governance-start` |
| Purpose | Basic source-of-truth and write authorization rules. |
| Owner | ChatGPT Orchestrator |
| Source of truth | GitHub Agent OS governance files |
| Files to read in order | 1. `AGENTS.md`<br>2. `00_Governance/ownership-and-source-of-truth.md`<br>3. `00_Governance/write-authorization-policy.md` |
| Stop condition | Stop after the system of record and write boundary are clear; if authorization or source of truth is unclear, stop and ask. |

### @agent-routing

| Field | Value |
|---|---|
| Alias | `@agent-routing` |
| Purpose | Identify the correct canonical job owner, legacy alias, and applicable shared standards/capabilities. |
| Owner | ChatGPT Orchestrator |
| Source of truth | Agent OS registry files in GitHub |
| Files to read in order | 1. `AGENTS.md`<br>2. `04_Registry/legacy-agent-alias-registry.md`<br>3. `04_Registry/agent-inheritance-registry.md`<br>4. `04_Registry/responsibility-matrix.md` |
| Stop condition | Stop after the canonical owner or capability route is identified. If no owner/standard is clear, recommend a registry update instead of inventing an agent. |

### @navigation-registry

| Field | Value |
|---|---|
| Alias | `@navigation-registry` |
| Purpose | Navigation Registry governance, lookup routing, or related repository implementation. |
| Owner | ChatGPT Orchestrator |
| Source of truth | GitHub shared navigation standard and registry files |
| Files to read in order | 1. `AGENTS.md`<br>2. `04_Registry/agent-inheritance-registry.md`<br>3. `04_Registry/responsibility-matrix.md`<br>4. `01_Shared_Standards/navigation/navigation-registry-standard.md`<br>5. `00_Governance/documentation-dependency-map/navigation-guide.md`<br>6. `02_Agent_Overlays/github-service-agent.md` only when repository implementation is required |
| Stop condition | Stop after routing, lookup scope, source-of-truth boundary, and write boundary are clear. Repository implementation routes to GitHub Service Agent; no cache/live-system mutation follows from lookup. |

### @github-change-request

| Field | Value |
|---|---|
| Alias | `@github-change-request` |
| Purpose | Prepare an authorized repository change handoff. |
| Owner | GitHub Service Agent |
| Source of truth | GitHub Change Request template and GitHub Service Agent overlay |
| Files to read in order | 1. `AGENTS.md`<br>2. `00_Governance/ownership-and-source-of-truth.md`<br>3. `00_Governance/write-authorization-policy.md`<br>4. `02_Agent_Overlays/github-service-agent.md`<br>5. `03_Templates/prompts/github-change-request.md` |
| Stop condition | Stop after target repository, branch, files, owner, permissions needed, acceptance criteria, validation evidence, risks, and blockers are clear. |

### @github-lean-start

| Field | Value |
|---|---|
| Alias | `@github-lean-start` |
| Purpose | Ordinary Tier 0/Tier 1 GitHub work. |
| Owner | GitHub Service Agent |
| Source of truth | GitHub Agent OS governance files |
| Files to read in order | 1. `AGENTS.md`<br>2. `00_Governance/write-authorization-policy.md`<br>3. `01_Shared_Standards/github/safe-implementation-lane.md`<br>4. `02_Agent_Overlays/github-service-agent.md`<br>5. `01_Shared_Standards/github/excluded-surface-baseline.md` |
| Stop condition | Stop after issue owner, source of truth, write boundary, bounded scope, and excluded surfaces are clear. |

### @remote-dev-validation

| Field | Value |
|---|---|
| Alias | `@remote-dev-validation` |
| Purpose | Discover the bounded GCE/IAP developer-validation and operator-console route when authorized Agent OS work needs checkout, Git, dependency, process, test, build/lint, runtime-inspection, or exact-head capabilities unavailable on the active surface. |
| Owner | ChatGPT Orchestrator for route discovery; GitHub Service Agent remains repository writer; QA / Test Agent owns validation evidence. |
| Source of truth | Safe Implementation Lane plus the fixed developer-validation identity, GitHub issue-comment ingress, and GCE/IAP transport contracts in GitHub. |
| Files to read in order | 1. `01_Shared_Standards/github/safe-implementation-lane.md`<br>2. `08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/dev_validation.py`<br>3. `08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/github_issue_comment_ingress.py`<br>4. `08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/dev_validation_gce.py` |
| Recognized intent phrases | `developer validation`, `remote validation`, `dev validate`, `validation VM`, `GCE executor`, `IAP SSH`, `SSH execution`, `SSH execution handoff`, `GitHub-SSH execution host`, and `A — LIGHTWEIGHT LANE` when the surrounding intent is bounded Agent OS developer-loop execution. `GitHub SSH` is ambiguous and must be resolved from intent rather than assumed to mean direct Git transport. |
| Distinguish from | Direct Git transport (`ssh git@github.com`), GitHub API/connector repository operations, Cloud Build validation, broader governed Scheduler/GCE execution, and Codespaces SSH. None is a synonym for this fixed-identity lane. |
| Negative rule | Local shell inability to reach `github.com`, absence of local SSH, or inability to use direct `ssh git@github.com` does not prove this governed GCE/IAP lane is unavailable. Resolve this alias before declaring required developer-loop execution unavailable. |
| Operator fallback | If the capable route is known but automatic dispatch is unavailable, name the governed GCE/IAP console/dev-validation route explicitly. A compact mobile/external-coding-agent handoff may preserve repository, issue/PR, branch/head, bounded scope, fixed validation identity/command, stop conditions, and required return evidence; it is operator UX only and grants no new authority. |
| Stop condition | Stop navigation after the bounded route and applicable fixed validation identity are known. Execution/continuation after discovery remains governed by the existing routing/continuation contracts (including #1237); do not invent arbitrary argv, a generic SSH shell, a second executor, or new write/merge authority. |

### @interaction-output

| Field | Value |
|---|---|
| Alias | `@interaction-output` |
| Purpose | Required report fields, presentation profile, and visible response ordering. |
| Owner | ChatGPT Orchestrator |
| Source of truth | GitHub shared global-engineering standards |
| Files to read in order | 1. `01_Shared_Standards/global-engineering/agent-interaction-output-standard.md`<br>2. `01_Shared_Standards/global-engineering/final-report-standard.md`<br>3. `02_Agent_Overlays/_common-overlay-rules.md`<br>4. `07_Agent_Tests/agent-output-schema.md` |
| Stop condition | Stop after profile, required fields, and ordering are clear. Presentation grants no execution, approval, or write authority. |

### @classroom-artifact-routing

| Field | Value |
|---|---|
| Alias | `@classroom-artifact-routing` |
| Purpose | Decide whether a lesson, slide deck, worksheet, or classroom artifact belongs in GitHub, Notion, or Google Drive. |
| Owner | Instructional Materials Coach |
| Source of truth | AGENTS.md destination rules and instructional materials overlay |
| Files to read in order | 1. `AGENTS.md`<br>2. `04_Registry/responsibility-matrix.md`<br>3. `02_Agent_Overlays/instructional-materials-coach.md`<br>4. `01_Shared_Standards/instructional-design/README.md` |
| Stop condition | Stop after the destination is clear. GitHub storage for classroom artifacts requires explicit approval and a GitHub Change Request handoff. |

## Version

0.3.0

## Changelog

- 0.3.0 adds `@remote-dev-validation`, disambiguates `GitHub SSH` from direct Git transport, and makes the existing bounded GCE/IAP developer-validation/console route discoverable without creating execution authority (#1514).
- 0.2.0 moves Navigation Registry and interaction-output alias ownership from retired Integration Manager references to ChatGPT Orchestrator (#1324).
