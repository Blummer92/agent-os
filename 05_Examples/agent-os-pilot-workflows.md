# Agent OS Pilot Workflows

## Purpose

Use these three pilots to test Agent OS in ChatGPT without trying to perfect every
agent at once.

## Pilot 1 - Lesson Planning

Route:

`Agent Orchestrator -> Unit Alignment Agent -> Teacher Modeling Coach -> Instructional Materials Coach`

Use when a teacher asks for a lesson plan, unit plan, modeling sequence, or
student-facing lesson draft.

Destination defaults:

- Planning records and lesson candidates: Notion handoff.
- Student-facing Docs, Slides, and worksheets: Drive after target folder approval.
- GitHub: only after explicit repository-storage approval.

Success checks:

- Correct owner selected.
- Subject areas treated as content domains, not agents.
- Standards, objectives, evidence target, and readiness gates identified.
- No student-facing artifact is created when production gates fail.

## Pilot 2 - Classroom Artifact

Route:

`Instructional Materials Coach -> Drive output -> QA / Test Agent`

Use when a lesson is ready to become a Doc, Slide deck, worksheet, checklist, or
classroom handout.

Destination defaults:

- Generated artifacts: confirmed Drive folder.
- QA notes and revision risks: local report or Notion handoff.
- Repository storage: GitHub Change Request only after explicit approval.

Success checks:

- Approved template or format identified.
- Drive target confirmed before writing.
- QA scores material-quality rows and names only failed rows.
- Revision scope stays limited to failed rubric rows.

## Pilot 3 - Repo Change

Route:

`ChatGPT Orchestrator -> GitHub Change Request -> GitHub Service Agent`

Use when Agent OS files, standards, overlays, templates, tests, or release notes
need repository storage.

Destination defaults:

- Agent OS system changes: GitHub branch and pull request.
- Classroom artifacts: Not GitHub unless explicitly approved.

Success checks:

- GitHub Change Request names repository, branch, files, owner, and acceptance criteria.
- GitHub Service Agent uses a non-main branch.
- Validation command is named and run when available.
- Final report includes files changed, tests run, docs updated, blockers, handoffs, and risks.

## Pilot Loop

After each pilot, record:

- What routed correctly.
- What destination was selected.
- What blocker or confusion appeared.
- What overlay, standard, template, or test should improve next.