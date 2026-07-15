# Instructional Materials Sources

## Purpose

Use this standard to choose, retrieve, and reconcile source context for classroom
material generation.

This file defines retrieval behavior. It does not serve as a Navigation Registry,
workspace map, dashboard catalog, or archive index.

## Source System Roles

- Notion: planning records, lesson notes, pacing context, readiness context, and
  source-of-truth records when designated by the current workflow.
- Google Drive: live lesson materials, worksheets, slides, handouts, unit guides,
  and shared working files.
- Google Sheets: canonical visual asset metadata when asset tracking is required.
- GitHub: Agent OS governance, standards, overlays, templates, registry files,
  tests, and release notes.
- Attached files and memory: reference snapshots unless the user explicitly asks
  to promote or refresh them.

## Classroom Curriculum Source Order

For classroom curriculum, lesson, slide, worksheet, image-library, assessment,
and instructional asset work, use this order unless the user explicitly names a
more specific current source:

1. Review Notion first for instructional intent, lesson sequence, featured
   photographers, existing lesson planning, unit alignment, readiness context,
   and other teacher-authored planning.
2. Review Google Drive second for approved or pending classroom assets, live
   slide decks, worksheets, photographs, examples, templates, and supporting
   media.
3. Use GitHub third for Agent OS governance, implementation, automation,
   testing, roadmap work, and change requests.

Notion is the authoritative source of instructional intent for classroom
curriculum work. Google Drive is the authoritative source for classroom asset and
material files. GitHub remains the authoritative source for Agent OS governance,
tooling, automation, implementation, and testing.

If Notion already contains instructional planning, extend or refine that work
rather than creating an entirely new lesson direction. If Notion and Google Drive
disagree, pause and document the conflict instead of guessing.

## Source Priority

Use this order when instructional sources overlap:

1. canonical unit or approved unit guide
2. current lesson plan, lesson brief, or teacher-authored current material
3. approved generation packet or teacher model
4. current working artifact being revised
5. templates and reusable support resources
6. archived or legacy material
7. attached files and memory snapshots

If sources conflict, prefer the designated live source. Do not write back a newer reality unless the task requires it and write access is approved.

## Notion Retrieval Standard

When Notion is involved:

- Use dashboards and hubs for routing, not as the primary instructional source.
- Follow linked pages and database relations before performing additional broad
  searches.
- Use the underlying unit, lesson, packet, or source page for content decisions.
- Prefer current and canonical records over templates, planning fragments, or
  archives.
- If two current sources are equally plausible and choosing wrong would change the work, ask one short clarification question.

## Conflict Resolution

When sources disagree:

- canonical unit guidance overrides lower-level generated artifacts
- current lesson guidance overrides slides, worksheets, and handouts
- teacher-authored current material overrides generated drafts
- current semester material overrides archived material
- explicit user direction in the current request overrides saved defaults

## Navigation Registry Boundary

Do not hard-code dashboard names, database names, archive locations, or one-off
retrieval paths in this standard. Those belong in a governed Navigation Registry
or in the current task context.

If a user names a specific page, folder, dashboard, database, or path, use that
named source as the retrieval target unless doing so conflicts with governance or
write authorization.

## Google Drive Retrieval Rules

Use Drive when the task needs existing slide decks, worksheets, Docs, unit guides,
or shared classroom files.

- Prefer current working files over copied or archived versions.
- Update an existing canonical working file by default when revising the same
  material.
- Create a separate copy only when requested, when the file is protected, when it
  sits outside the confirmed target workspace, or when preserving the original
  materially matters.

## Asset Metadata Rules

Check the canonical asset sheet before creating or updating visual metadata.

Required record groups:

- identifiers: Asset ID, Asset Name, Drive Link
- classification: Folder, Asset Type, Best-Fit Unit, Lesson / Use Case
- status: Student-Facing?, Teacher-Facing?, Quality / Readiness, Source / Permission Status, Duplicate Status, Keep Decision
- tracking: Notes for Future Agents, Source Authority, Approval Status, Last Updated, Next Action, Migration Notes

Search by Asset ID first. Update matching rows instead of duplicating. If no
match exists, append a complete row. Do not invent unknown required values.

## Lightweight Curriculum Validation

Before producing governed classroom artifacts or implementation changes, confirm:

- Notion instructional planning was reviewed.
- Google Drive assets were reviewed when assets or existing materials are needed.
- GitHub change necessity was evaluated.
- No new lesson direction was introduced without reconciling with Notion.
- Any Notion, Drive, or GitHub source conflicts were documented.

If any item cannot be confirmed, pause before producing final governed artifacts
or implementation changes. This checklist is not required for casual
brainstorming or exploratory conversations.

## Version

0.1.3

## Changelog

- 0.1.3 added Classroom Curriculum Source Order and lightweight curriculum validation.
- 0.1.2 added asset metadata rules for canonical visual asset tracking.
