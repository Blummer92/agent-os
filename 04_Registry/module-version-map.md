# Module Version Map
Module versions are governed by `00_Governance/standards-change-control.md`; repository releases and module versions are independent.

| Module | Version |
|---|---|
| Global Engineering | 0.4.0 |
| Agent Interaction Output Standard | 0.2.0 |
| Testing And Release | 0.3.0 |
| Read-Only Default | 0.1.0 |
| Source-of-Truth Checks | 0.1.0 |
| Python Standards | 0.1.0 |
| Google Workspace Standards | 0.1.2 |
| Apps Script Standards | 0.1.0 |
| Notion Standards | 0.4.0 |
| QA/Test Standards | 0.1.0 |
| Dashboard Governance | 0.1.0 |
| Dashboard Migration Verification | 0.1.0 |
| Instructional Design Standards | 0.16.0 |
| Agent Orchestrator | 0.3.0 |
| GitHub Service Agent | 0.7.0 |
| Unit Alignment Agent | 0.6.0 |
| Teacher Modeling Coach | 0.6.0 |
| Instructional Materials Coach | 0.5.1 |
| QA / Test Agent | 0.2.1 |
| Student Language Standard | 0.3.0 |
| Workflow Scheduler | 0.18.0 |
| Workspace Automation Builder Tooling | 0.1.1 |
| Agent Memory & Context Budget Manager | 0.1.0 |
| IA4D-to-Scheduler Handoff Contract | 0.2.0 |
| GitHub Issue Lifecycle Standard | 0.3.0 |
| Safe Implementation Lane | 0.7.0 |
| Agent OS Execution Service | 0.6.0 |
| Artifact-First Response Standard | 0.1.0 |
| Teacher Decision Studio Standard | 0.1.0 |
| LP Pacing Handoff Contract | 0.1.0 |
| LP Reason Code Catalog | 0.1.0 |
| LP Notion Working Layer | 0.1.0 |
| Agent OS Codespaces Profile | 0.2.0 |
| Execution Checkpoint Contract | 0.1.0 |
| Issue Quality Taxonomy | 0.1.0 |

**Global Engineering** `0.4.0` adds the Pattern + Docs Freshness Gate to repository implementation final reports and GitHub Change Request handoffs while preserving Agent Interaction Output Standard ownership of report fields and presentation order (#998; planned in #928, PR #929).

**Agent Interaction Output Standard** `0.2.0` adds compact state-based operator rendering for implementation and PR review (#1081): bounded stage bars without invented percentages, canonical `Completed` / `Current` / `Remaining` / `Blockers` evidence labels, material-only `Best execution`, supported `Next`, and smallest-context delivery; no new progress state or authority.

**Safe Implementation Lane** `0.7.0` adds opt-in Terminal Fast Lane (#1309) by composing the canonical #924 `request-interpretation-v1` record, existing `operating_mode.py` `RequestedMode.RELEASE` ceiling, existing #1187 branch refresh, and existing `agent-os-release-run.py` terminal progression for eligible Tier 0/1 `no-external-write` work. The Orchestrator does not add a second raw-language parser, and no new lifecycle stage, router, merge/closure authority model, or Scheduler is introduced. This registry entry was previously stale at `0.5.0` against the standard's own `0.6.0` (#1274); `0.6.0` distinguished artifact non-authority from later direct-owner authorization and carried one instruction across a single mechanical readiness intervention. `0.5.0` composed existing #895 checkpoint/resume and #758 Scheduler lease evidence into resumable authorized work, distinguished same-branch `HEAD_ADVANCED` from #1187 base-behind refresh, and required current replacement evidence before cancelled stale-head validation was treated as superseded (#1188).

**Notion Standards** `0.4.0` defines the canonical Draft Mode, Append-Only Safe Log Mode, and Canonical Update Mode write-safety vocabulary in `notion-record-update-safety.md` (#1103). Mode classification never creates authority; existing write authorization remains canonical in `00_Governance/write-authorization-policy.md`.

**Instructional Design Standards** `0.16.0` adds the synthetic/noncanonical Unit 0 Assessment Reference Validation Standard (#842), composing #837/#838/#1192/#839/#841/#843 through focused integration fixtures without redefining upstream semantics or creating canonical curriculum content. `0.15.0` added the Assessment Dashboard Workspace Standard (#843); `0.14.0` added the Assessment QA and Evidence Review Standard (#841); `0.13.0` added the Assessment Sequencing and Student Experience Standard (#839); `0.12.0` added the Assessment Blueprint Lifecycle Standard (#1192); `0.11.0` added the Assessment Blueprint Core Standard (#838); `0.10.0` integrated the Unit Creation Conversational Contract (#1214). These changes create no Assessment Agent and authorize no grading, readiness, classroom use, production, publication, or external writes.

**QA / Test Agent** `0.2.1` binds assessment QA work to the #841 Assessment QA and Evidence Review Standard while preserving the post-#1324 canonical technical validation/evidence role, GitHub Service Agent repository-write ownership, and existing non-authorizing boundaries. `0.2.0` aligned the overlay with the post-#1324 technical architecture (#1342).

**Dashboard Migration Verification** (`08_Tooling/dashboard-migration-verification/`) is a verification-only migration evidence toolkit for registry examples, placeholder snapshots, dependency graphs, conservative validation results, and reports. It never authorizes live Notion, Workspace, trigger, sharing, source-of-truth, or production dashboard writes. Standard packaging metadata was completed by D2 (#123).

**Workspace Automation Builder Tooling** (`08_Tooling/workspace-automation-builder/`) includes an Apps Script safety bridge, offline tests, sync safety docs, sanitized sample handoff fixture, JSON schemas, validation fixtures, and a local-only fixture validator. It does not authorize live Workspace, Notion, trigger, sharing, or production writes.

**Workflow Scheduler**, **Agent Memory & Context Budget Manager**, **IA4D-to-Scheduler Handoff Contract**, and **Agent OS Execution Service** extended descriptions live in `04_Registry/module-version-map-details.md`. Workflow Scheduler moved to `0.10.0` under #758 for the additive host-local concurrency-1 lease adapter, `0.11.0` under #759 for opt-in Linux cgroup v2 containment, `0.12.0` under #760 for complete workspace-state evidence, `0.13.0` under #762 for authorized-validation runtime composition, `0.14.0` under #722 for the pure bounded Claude Code invocation/result adapter, `0.15.0` under #1185 for task-scoped dependency readiness and deterministic Python/npm preparation, and `0.16.0` under #1205 (AOS-VALTERM1) for explicit validation-process termination evidence (`CommandRunObservation`/`FrozenTestValidationResult`/`PilotValidationObservation` additive fields); it moved to `0.18.0` under #1300 (AOS-GCE2C) for packaging only, declaring the canonical repository-root `scripts.*` contract packages its runtime already imports plus its `PyYAML`/`reusable-capability-registry` dependencies. Agent OS Execution Service stays `0.6.0` under #762 because that version is bound to the runtime identity constant `EXECUTION_SERVICE_VERSION`; #1300 changed only its packaging metadata, adding deterministic `workflow-scheduler`/`agent-memory-context-manager`/`PyGithub`/`requests` runtime dependencies and distributing `scripts.agent_os_candidate_packet`/`scripts.agent_os_github_issue_provider`.

**Instructional Materials Coach** `0.4.0` adds `curriculum-visual-asset-compatibility-v2` and `curriculum-visual-asset-candidates-v2` (#871), preserving v1 mappings, defaults, identities, and non-authorizing behavior. `0.5.0` adds `curriculum-image-intent-v1` and `curriculum-imported-asset-context-v1` (#955), keeping provider prompt prose noncanonical and provenance user-claimed. `0.5.1` clarifies that Notion remains Draft Mode by default and no Append-Only Safe Log Mode or general Notion-write authority is inherited automatically (#1103).

**Artifact-First Response Standard** (`01_Shared_Standards/instructional-design/artifact-first-response-standard.md`, #821) requires classroom-material responses to lead with the requested artifact, preview, or content specification before backend routing and governance reporting while preserving existing gates, ownership, and stops.

**Teacher Decision Studio Standard** (`01_Shared_Standards/instructional-design/teacher-decision-studio-standard.md` plus `teacher-decision-studio-previews-standard.md`, #823/#824) defines table-first rubric/assessment consultation, explanation-risk analysis, and per-option previews; it recommends without auto-approving or writing governed fields.

**LP Pacing Handoff Contract** (`01_Shared_Standards/instructional-design/lp-pacing-handoff-contract.md`, adaptation/cases companions, and `04_Registry/lp-pacing-handoff-contract.yaml`, #648) defines the provider-neutral pacing packet, owner-state independence, diagnosis, and adaptation hierarchy; it authorizes no runtime evaluator, OCR, classroom data, external write, or gate advancement.

**LP Reason Code Catalog** (`01_Shared_Standards/instructional-design/lp-reason-code-catalog.md` and `04_Registry/lp-reason-code-catalog.yaml`, #711) owns the finite `lp-*` semantic reason catalog and producer/consumer map; parsing, bounds, serialization, and authority mechanics remain with LP9, LP12, and CW5A.

**LP Notion Working Layer** (`01_Shared_Standards/notion/lp-notion-working-layer-standard.md` and `04_Registry/lp-notion-working-layer-change-request.yaml`, #652) defines the bounded Notion working-layer design and exact-target Change Request; it remains proposed/not authorized with six unresolved decisions.

**Execution Checkpoint Contract** (`scripts/agent_os_execution_checkpoint/`, #895, design approved in #858) is the pure-local checkpoint record, content-addressed append-only storage, and resume planner; every authority field stays false. Its canonical source location and ownership are unchanged by #1300 (AOS-GCE2C); that issue only made the same files installable by declaring them in the `workflow-scheduler` distribution, so exactly one implementation of the descriptor loader continues to exist. #1304 (AOS-GCE2E) additively closed the ResumePlan round-trip and checkpoint-by-id gaps here (`resume_plan_from_dict`/`serialize_resume_plan`/`deserialize_resume_plan`, `resume_plan_store.py`, `store.load_checkpoint_by_id`) and added the sibling #918 route-decision/handoff stores under `agent-os-execution-service`; no package metadata or version changed.

**GitHub Issue Lifecycle Standard** `0.3.0` adds Promotion In Place as a canonical issue-body classification using the existing Child-Issue Creation Test and explicitly forbids a parallel promotion issue-state snapshot/model; it also generalizes the volatile-execution-facts restriction beyond Level 1 roadmap issues (#1309).

**GitHub Service Agent** `0.7.0` consumes a fresh canonical Terminal Fast Lane request interpretation as a bounded authorization input for eligible Tier 0/1 `no-external-write` work, while existing `operating_mode.py`, exact-head, merge/review, closure, and excluded-surface gates remain authoritative (#1309).

## Reconciliation Notes
A3 reviewed this map against visible repository evidence only. Runtime status not directly supported by files or validation evidence remains unstated.