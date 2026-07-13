# Agent OS Pilot Prompts

## Lesson Planning Pilot

```text
Use Agent OS.

Repository: `Blummer92/agent-os`
Branch: `main`
Start from `AGENTS.md`.

Task: create a 9th grade digital media lesson on typography and color theory.

Before drafting, route the task:
- identify the task owner and selected overlay
- treat typography and color theory as content domains, not agents
- identify standards and readiness gates
- decide whether the destination is Notion, Drive, or GitHub
- do not write anywhere until the target is approved

Output routing decision, lesson draft, blockers, handoff needed, and next action.
```

## Classroom Artifact Pilot

```text
Use Agent OS.

Take the approved lesson plan and prepare student-facing classroom materials.

Before creating files:
- route to Instructional Materials Coach
- confirm the approved template or format
- ask for the Google Drive target folder
- identify QA / Test Agent review criteria
- do not write to GitHub unless repository storage is explicitly approved

Output artifact plan, Drive target needed, QA checklist, blockers, and next action.
```

## Repo Change Pilot

```text
Use Agent OS.

Prepare a GitHub Change Request for an approved Agent OS repository change.

Before writing to GitHub:
- route through ChatGPT Orchestrator
- use `03_Templates/prompts/github-change-request.md`
- identify repository, branch, target files, owner, acceptance criteria, and risks
- route implementation only to GitHub Service Agent
- never push directly to `main`

Output the complete handoff packet and stop for approval unless approval is already explicit.
```

## Pilot Debrief Prompt

```text
Use Agent OS.

Review the last pilot run.

Report:
- owner selected
- overlays and standards read
- destination selected
- writes allowed and blocked
- output quality issues
- missing rules or tests
- recommended Agent OS improvement
```
