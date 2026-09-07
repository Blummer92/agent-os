# AGENTS.md
## Purpose
This file is the ChatGPT entry point for Agent OS: the governed knowledge base
for agent standards, overlays, templates, registry maps, examples, tests, and
release notes.

## Source Of Truth
GitHub is the canonical source of truth for Agent OS. ChatGPT is an execution
interface, not the source of truth.

Notion, Google Drive, and ChatGPT memory are secondary working surfaces unless a
governance-approved source-of-truth change says otherwise.

## Classroom Artifact Destinations
Agent OS governance, standards, overlays, registry files, templates, tests, and
release notes default to GitHub.

Teacher planning, readiness status, lesson candidates, and working knowledge
default to Notion or a Notion handoff.

Student-facing Slides, Docs, worksheets, and generated classroom materials
default to approved Google Drive folders.

GitHub storage for lessons or classroom artifacts requires explicit user approval
and a GitHub Change Request handoff.

Do not route classroom artifacts to GitHub just because Agent OS itself lives in
GitHub.

## Start Here
Before doing Agent OS work, read only the files needed for the exact next action:

1. `00_Governance/ownership-and-source-of-truth.md`
2. `00_Governance/write-authorization-policy.md`
3. `04_Registry/agent-inheritance-registry.md`
4. `04_Registry/responsibility-matrix.md`
5. the relevant file in `02_Agent_Overlays/`
6. only shared standards whose existing applicability trigger is met

Use `04_Registry/navigation-alias-registry.md` when a common Agent OS path needs resolution; do not preload it. When the user names or clearly refers to an Agent OS capability/path such as `GitHub SSH`, remote developer validation, the validation VM, GCE/IAP execution, or another registered/common route, resolve that path through the Navigation Alias Registry before declaring the capability unavailable from the literal active tool/action list. Absence of a same-named local tool or command is surface evidence only; it is not proof that the registered Agent OS capability is unavailable. After resolution, apply the owning capability and #1237 continuation/currentness rules rather than treating alias lookup itself as execution authority. Reuse unchanged same-lineage facts, but reacquire mutable authorization, issue, PR/head/base, validation, review, and execution/lease evidence when its canonical freshness contract requires it.

## Agent Selection
Use agents for repeatable jobs, not every subject area. Video production,
photography, typography, color theory, graphic design, and AI learning are
content domains unless a governed change promotes one into a real repeatable
agent role.

Legacy agent names, old Notion agent-property values, and superseded workflow
labels are acceptable user input only when they resolve through
`04_Registry/legacy-agent-alias-registry.md`. Legacy aliases do not create
executable agents — they resolve to canonical agents listed in
`04_Registry/agent-inheritance-registry.md`, and only those canonical agents
execute.

## Access Rules
Default to read-only when authorization, target, or source of truth is unclear.

Only the GitHub Service Agent may write to GitHub. All non-GitHub agents must
create a GitHub Change Request handoff when repository changes are needed.

Do not modify production systems, governed fields, sharing settings, source-of-
truth records, or irreversible artifacts without explicit approval.

## ChatGPT Workflow
1. Identify the task owner and resolve legacy aliases only when present.
2. Read the owner overlay and only applicable standards; use the smallest useful context packet.
3. Confirm allowed/blocked write surfaces and stop if authorization or source of truth is unclear.
4. Before forming the first substantial investigation, implementation, or repair hypothesis for an Agent OS mission, run the existing ChatGPT Orchestrator Coding Lessons Learned Preflight using the smallest current `CodingKnowledgeRequest`. Record the bounded CKR6 outcome even when it is `not-needed` or an allowed unavailable-safe-fallback; investigation-only work does not bypass this entry condition merely because no repository mutation has occurred. Reuse that preflight while the mission signals remain materially unchanged. When a newly discovered blocker, failure, target-path change, or architecture finding materially changes those signals, re-evaluate the existing preflight before forming the next materially different hypothesis; do not repeat broad retrieval after every read-only lookup. GitHub remains authoritative and selected lessons remain advisory-only. A failed implementation/repair attempt additionally follows the retry-specific step below; this initial/investigation preflight never substitutes for #1988 failed-repair re-entry.
5. Resolve ambiguous shorthand against the active unfinished parent mission before selecting a new target. When the active mission is current-PR cleanup or repair, rank and reacquire that current PR queue before considering unrelated backlog issues; explicit requests to work or discover the issue backlog still select the backlog normally.
6. For a direct single-target `Work on <number>` or `Fix <number>` mission, identifier verification, diagnosis, and historical-state classification are routing evidence, not terminal outcomes. If the supplied number resolves to a merged PR, closed/completed issue, stale historical branch, or other non-current lineage artifact, continue the same bounded mission through current GitHub truth to the current actionable issue/PR/successor when existing authorization and Safe Implementation Lane rules permit it. Diagnosis alone is never completion. Do not terminate on an intermediate state equivalent to `I'm checking`, `I'm tracing`, or `likely mismatch`. The mission may stop only after one governed terminal disposition is proven: current work completed or advanced; an existing current PR resumed; a current actionable successor identified and advanced under still-applicable authorization; current `main` proven to already satisfy the requested contract with concrete implementation and validation evidence; a specific authorization/governance/external-capability blocker identified; or manual review required after bounded escalation leaves ownership/identity genuinely ambiguous. Historical classification never reopens an issue, creates a successor, widens scope, or grants excluded-surface authority by itself. Reuse the finite-mission continuation semantics already used for bounded bug batches rather than creating another scheduler, queue, or state model, and always emit the required final report for the terminal disposition.
7. For bounded bug-work requests, reconcile the existing discovered/open bug backlog before fresh defect discovery. Exclude stale, duplicate, already-fixed, active-implementation, non-repository, blocked, or unauthorized candidates; use eligible existing bugs first, and discover new bugs only when the reconciled backlog cannot satisfy the requested count or the user explicitly requests new bugs. Do not create issues merely to pad a requested count. Bind each candidate disposition to the existing finite-mission cursor: already-fixed/completed, duplicate, blocked-item-local, separately-gated, external-owner/non-repository, and other candidate-local terminal dispositions are non-terminal for the parent batch and must immediately advance to the next independent candidate without another user prompt or rebuilding the batch investigation. Stop later candidates only for a shared authorization, source-of-truth, bounded-scope, excluded-surface, capability, or material-decision blocker; otherwise continue until the requested count is worked or the reconciled pool is exhausted and report the honest shortfall.
8. When a process/tooling bug is discovered and logged during an unfinished authorized mission, treat bug capture as subordinate bookkeeping rather than a terminal outcome. After the bounded bug write or alternate canonical persistence route completes, reacquire the parent issue/PR/branch/head checkpoint and continue the still-authorized parent mission without requiring another user prompt. Stop only when the discovered bug creates a genuine shared authorization, source-of-truth, bounded-scope, excluded-surface, capability, or material-decision blocker.
9. Treat every successful subordinate GitHub mutation during an unfinished finite mission — including an issue/PR comment, label mutation, handoff record, or evidence-persistence write — as provisional intermediate evidence, never as parent-mission completion by itself. Read back the canonical mutated target to prove persistence/currentness, then reacquire the parent issue/PR/branch/head/CI checkpoint when those mutable facts govern remaining work. Continue the still-authorized parent mission automatically while in-scope work remains. Stop only at an existing governed terminal disposition or a genuine authorization, source-of-truth, bounded-scope, excluded-surface, capability, or material-decision blocker. This readback/continuation step never widens authority and never grants merge, issue-closure, workflow/protected-setting, credential, production, or external-write authority.
10. When a governed implementation or PR repair attempt remains red or otherwise fails, the next repair hypothesis or repository mutation is gated by `01_Shared_Standards/global-engineering/failed-repair-lesson-reentry.md`. Preserve the failed attempt, increase diagnostic resolution, satisfy that shared standard's existing retry-specific CKR6 re-entry and mutation-admission contract, then reacquire mutable GitHub state before continuing. Every newly failed attempt re-triggers this step; an earlier lesson outcome cannot satisfy a later failed attempt. Do not substitute the ordinary one-time coding preflight for this retry transition.
11. For eligible Safe Implementation Lane work, route registered-owner transitions internally while authorization, source of truth, and bounded scope remain applicable; do not require a user copy/paste handoff only because the owner changes.
12. Surface a handoff or decision only when authorization, source of truth, bounded scope, or a material decision changes.

## Required Final Report
`01_Shared_Standards/global-engineering/agent-interaction-output-standard.md` is the canonical owner of report field ownership and presentation. Implementation/review reports must include files changed, tests run, docs updated, unresolved blockers, handoff recommendations, and remaining risks. Eligible Safe Implementation Lane work also follows its `Reporting` contract for actual branch, exact-head evidence, rollback, and authorization/excluded-surface confirmation.

## GitHub Handoffs
Use `03_Templates/prompts/github-change-request.md` for repository changes requested by a non-GitHub agent. An already-authorized Safe Implementation Lane handoff may remain internal while ChatGPT continues through the GitHub Service Agent; otherwise surface it for the required user decision. The GitHub Service Agent owns branch, commit, pull request, validation, and final GitHub reporting.
