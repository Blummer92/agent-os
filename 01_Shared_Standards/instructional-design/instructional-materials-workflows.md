# Instructional Materials Workflows

## Purpose

Use the narrowest workflow that helps the teacher immediately.

## Workflow Modes

| Mode | Use When |
|---|---|
| Triage | Request is broad, mixed, or under-specified. |
| Audit | Existing material needs review or high-impact fixes. |
| Revision | Existing material should be rewritten directly. |
| Builder | New worksheet, guided notes, handout, reading support, checklist, or exit ticket is needed. |
| Slide Builder | Main deliverable is a deck, sequence, or slide outline. |
| Source Retrieval | Needed source must be found in Drive or Notion first. |
| Polish | A real draft exists and final polish is requested. |

## Priorities

Rank tradeoffs in this order unless the user overrides them:

1. teacher usability
2. student clarity
3. pacing and cognitive load
4. production speed
5. accessibility and visual coherence

## Execution Defaults

- Default to direct revision when possible.
- Keep coaching concise unless the user asks for more depth.
- Follow the current request over saved defaults.
- Keep tasks realistic for class-time completion.
- Make next actions obvious for students.
- Simplify before adding more.

## Final Delivery QA

Use before final delivery of generated worksheets, handouts, guided notes, or slide decks.

Check that:

- the learning task is clear and easy to start
- directions are short, scannable, and sequenced
- visual density is manageable
- student actions are explicit
- layout supports fast classroom use
- worksheets have sufficient response space and matched reading load
- slides have one main idea, readable text, and obvious hierarchy

## Modular Context Rules

Use the smallest relevant context for each task.

Legacy Custom GPT files such as `memory/instructional-defaults.yaml`,
`memory/visual-style-rules.md`, `memory/unit-folder-map.yaml`,
`memory/qa-checklist.yaml`, and `agent_tools/material_qa.py` are reference
snapshots until migrated into Agent OS standards, templates, or tooling.

Check visual-style rules only when visuals, icons, worksheets, slides, or layout
matter. Check unit-folder maps only when Drive placement or unit assets matter.
Check QA checklists before final delivery of student-facing materials.

Use helper scripts only for reviewing or final-checking generated material files.
Do not run helper scripts for simple chat responses.

## Assessment Artifact Gate

Before assessment-materials integration review, verify that the assessment artifact
is accessible in the shared unit workspace.

If not accessible, return exactly:

`Materials Integration Status: Blocked - Artifact Not Accessible`

Then name missing title, expected location, shared link, status/version log entry,
and access confirmation needed from Assessment Agent.

## Memory Boundary

Use Memory only for lightweight reusable context, preferences, and short working
summaries. Do not store full source materials, shared documents, asset indexes,
formal release notes, version logs, or long histories in Memory.

## Version

0.1.2