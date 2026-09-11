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

### @notion-lessons-learned

| Field | Value |
|---|---|
| Alias | `@notion-lessons-learned` |
| Purpose | Resolve Agent OS Lessons Learned and other bounded Notion working-knowledge reads from ChatGPT without assuming the native/direct ChatGPT Notion connector is the only capability path. |
| Owner | ChatGPT Orchestrator for route discovery; GitHub Service Agent owns repository transport implementation; QA / Test Agent owns validation evidence. |
| Source of truth | GitHub governs the route and contracts; Notion remains the working source for Lessons Learned and authorized working knowledge. |
| Files to read in order | 1. `AGENTS.md`<br>2. `02_Agent_Overlays/chatgpt-orchestrator.md`<br>3. `08_Tooling/agent-memory-context-manager/CKR6_LESSON_PREFLIGHT.md`<br>4. `01_Shared_Standards/notion/notion-learning-databases.md`<br>5. `docs/2283-github-notion-read-path.md` |
| Recognized intent phrases | `Notion Lessons Learned`, `Lessons Learned`, `coding lessons learned`, `update the Notion learned lessons`, `Notion working knowledge`, and requests that explicitly refer to the GitHub MCP / Agent OS path to Notion. |
| Distinguish from | The native/direct ChatGPT Notion plugin, generic workspace search, GitHub-hosted curriculum/lesson storage, or unrestricted Notion API access. The direct plugin is one possible transport surface, not capability truth. |
| Negative rule | A disabled, missing, disconnected, or unsupported native ChatGPT Notion plugin does not prove the governed Agent OS Notion capability is unavailable. Resolve this alias and inspect the current GitHub-controlled route before reporting a Notion capability blocker. |
| Write-intent rule | `update`, `write`, `save`, or other mutation intent may resolve through this alias for capability discovery, but `docs/2283-github-notion-read-path.md` proves only the bounded read route. Never infer Notion write reachability from that read route. Before continuing a mutation request, separately resolve the applicable Notion write authorization and a current write-capable execution surface; if either is unavailable, report that exact blocker. |
| Continuation rule | Successful route discovery is intermediate evidence. Continue the parent mission through the currently authorized route appropriate to the requested operation. Read requests may use the governed read path; write requests continue only after separate write authorization and write-capable execution-surface evidence are established. Do not stop merely because the direct plugin is unavailable. |
| Stop condition | Stop only after the current governed Notion route, authorization boundary, and execution-surface availability are known. Alias resolution itself grants no Notion write, schema, credential, sharing, workflow, production, merge, or issue-closure authority. |

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

0.4.0

## Changelog

- 0.4.0 adds `@notion-lessons-learned` so ChatGPT resolves the governed GitHub MCP / Agent OS Notion route before treating native/direct Notion plugin unavailability as a terminal capability result (#2301). Write intents are explicitly separated from the #2283 read-only route and require independent write authorization plus write-capable execution-surface evidence.
- 0.3.0 adds `@remote-dev-validation`, disambiguates `GitHub SSH` from direct Git transport, and makes the existing bounded GCE/IAP developer-validation/console route discoverable without creating execution authority (#1514).
- 0.2.0 moves Navigation Registry and interaction-output alias ownership from retired Integration Manager references to ChatGPT Orchestrator (#1324).