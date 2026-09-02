# AGENTS.md
## Purpose
This file is the ChatGPT entry point for Agent OS: the governed knowledge base
for agent standards, overlays, templates, registry maps, examples, tests, and
release notes.

## Source Of Truth
GitHub is the canonical source of truth for Agent OS. ChatGPT is an execution
interface, not the source of truth.

Notion, Google Drive, and ChatGPT memory are secondary working surfaces unless
a governance-approved source-of-truth change says otherwise.

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
Before doing Agent OS work, read only the files needed for the task:

Agents should consult `04_Registry/navigation-alias-registry.md` before manually searching for common Agent OS documentation paths.

1. `00_Governance/ownership-and-source-of-truth.md`
2. `00_Governance/write-authorization-policy.md`
3. `04_Registry/agent-inheritance-registry.md`
4. `04_Registry/responsibility-matrix.md`
5. the relevant file in `02_Agent_Overlays/`
6. any shared standards referenced by that overlay that are applicable to the exact next action

Do not preload every standard referenced by an overlay merely because the reference exists. Determine applicability from the resolved task, canonical owner, current issue/lineage evidence, and exact next action; load conditional standards only when their existing canonical trigger applies.

### Routine Repository Coding Hot Context
For one ordinary Tier 0/1 `status:ready`, `no-external-write` GitHub issue with one focused objective, resolved ownership, no material blocker, no active/ambiguous execution conflict, and a fresh direct repository-owner implementation instruction, the routine pre-implementation context is bounded to: canonical request interpretation; live issue/readiness/scope/source-of-truth evidence; canonical owner/write boundary; Safe Implementation Lane and excluded-surface admission; existing branch/PR lineage when present; and the validation obligations needed for the next lifecycle transition.

The following are conditional side paths, not routine preload requirements: Decision/ADR retrieval only when CKR10 returns `retrieval_required=true`; Lessons Learned retrieval only when CKR6/CKR11 requires material use; runtime/executor details only when the exact next action needs capabilities unavailable on the connected surface; checkpoint/`ResumePlan` and Scheduler lease only for existing runtime/resume/concurrency lineage; branch-refresh rules only when live evidence proves the branch needs the governed refresh path; PR-remediation rules only for actual PR/CI/review repair; finite-mission rules only for explicit multi-item missions; Terminal Fast Lane only for canonical structured release mode; and classroom/PPUX routing only for requests resolved to those domains.

Reuse immutable same-lineage facts instead of rediscovering them. Reacquire mutable evidence when its canonical contract requires freshness, including issue state, authorization applicability, PR/head/base, validation, reviews, and active execution/lease state. Do not create a second task-state packet, cache, router, authorization model, or context manager to implement this boundary.

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
1. Identify the task owner.
2. Resolve any legacy agent aliases through `04_Registry/legacy-agent-alias-registry.md`.
3. Read the owner overlay and only the referenced standards applicable to the exact task/next action.
4. Confirm allowed and blocked write surfaces.
5. Use the smallest useful context packet.
6. Stop if authorization or source of truth is unclear.
7. For eligible Safe Implementation Lane repository work, route registered-owner
   transitions internally while the current authorization, source of truth, and
   bounded scope remain applicable; do not require a user copy/paste handoff only
   because the responsible owner changes.
8. Surface a handoff or decision when authorization, source of truth, bounded
   scope, or a material decision changes.

If a legacy alias maps to a canonical agent, continue normal routing and report the
alias resolution. If no alias exists, stop and recommend a registry update.

## Required Final Report
`01_Shared_Standards/global-engineering/agent-interaction-output-standard.md` is
the canonical owner of report field ownership, presentation profiles, visible
ordering, and progress labeling. This entry point restates only its minimum:
every implementation or review report must include files changed, tests run,
docs updated, blockers, handoff recommendations, and remaining risks.
For eligible Safe Implementation Lane work, also follow the `Reporting` contract
in `01_Shared_Standards/github/safe-implementation-lane.md`: actual branch,
exact-head evidence, rollback, and authorization/excluded-surface confirmation.

## GitHub Handoffs
Use `03_Templates/prompts/github-change-request.md` for any repository change
requested by a non-GitHub agent. For eligible Safe Implementation Lane work that
is already authorized, the handoff may remain an internal routing/audit artifact
while ChatGPT continues through the GitHub Service Agent in the same interaction.
Otherwise surface the handoff for the required user decision. The GitHub Service
Agent decides the branch, commit, pull request, validation, and final GitHub
report.
