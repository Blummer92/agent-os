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
Before doing Agent OS work, read only the files needed for the exact next action:

1. `00_Governance/ownership-and-source-of-truth.md`
2. `00_Governance/write-authorization-policy.md`
3. `04_Registry/agent-inheritance-registry.md`
4. `04_Registry/responsibility-matrix.md`
5. the relevant file in `02_Agent_Overlays/`
6. only shared standards whose existing applicability trigger is met

Use `04_Registry/navigation-alias-registry.md` when a common Agent OS path needs resolution; do not preload it. Reuse unchanged same-lineage facts, but reacquire mutable authorization, issue, PR/head/base, validation, review, and execution/lease evidence when its canonical freshness contract requires it.

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
4. For eligible Safe Implementation Lane work, route registered-owner transitions internally while authorization, source of truth, and bounded scope remain applicable; do not require a user copy/paste handoff only because the owner changes.
5. Surface a handoff or decision only when authorization, source of truth, bounded scope, or a material decision changes.

## Required Final Report
`01_Shared_Standards/global-engineering/agent-interaction-output-standard.md` is the canonical owner of report field ownership and presentation. Implementation/review reports must include files changed, tests run, docs updated, unresolved blockers, handoff recommendations, and remaining risks. Eligible Safe Implementation Lane work also follows its `Reporting` contract for actual branch, exact-head evidence, rollback, and authorization/excluded-surface confirmation.

## GitHub Handoffs
Use `03_Templates/prompts/github-change-request.md` for repository changes requested by a non-GitHub agent. An already-authorized Safe Implementation Lane handoff may remain internal while ChatGPT continues through the GitHub Service Agent; otherwise surface it for the required user decision. The GitHub Service Agent owns branch, commit, pull request, validation, and final GitHub reporting.
