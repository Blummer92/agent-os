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

## Version

0.1.2
