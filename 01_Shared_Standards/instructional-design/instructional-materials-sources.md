# Instructional Materials Sources

## Purpose
Use this standard to choose, retrieve, and reconcile source context for classroom
material generation. This file defines retrieval behavior; it is not a
Navigation Registry, workspace map, dashboard catalog, or archive index.
## Source System Roles
- Notion: instructional intent, planning records, and the teacher-facing Visual
  Asset Library working registry, including discovery, relationships, review
  notes, and projections.
- Google Drive: live classroom materials plus binary asset storage and stable
  external file identity.
- Google Sheets: review or reconciliation evidence only when that lane is
  active; it is not the canonical Visual Asset Library or validated visual
  evidence contract.
- GitHub: Agent OS governance, controlled vocabulary, validators, fixtures,
  tests, tooling, registry files, and release notes.
- Attached files and memory: reference snapshots unless the user explicitly
  asks to promote or refresh them.
## Classroom Curriculum Source Order
For curriculum, lesson, slide, worksheet, image-library, assessment, and
instructional asset work, use this order unless the user names a more specific
current source:
1. Review Notion first for instructional intent, lesson sequence, featured
   photographers, lesson planning, unit alignment, readiness, and Visual Asset
   Library working records.
2. Review Google Drive second for approved or pending assets, live materials,
   photographs, examples, templates, media, and exact file identity.
3. Use GitHub third for governance, contract behavior, implementation,
   automation, testing, roadmap work, and change requests.

Notion is authoritative for instructional intent and teacher-facing asset
working records. Drive is authoritative for classroom files and binary asset
identity. GitHub is authoritative for Agent OS governance and validated contract
behavior. If Notion and Drive disagree, pause and document the conflict.
## Visual Asset Evidence Ownership
For governed reusable visuals:
- `ArtifactManifest` is the canonical validated evidence for rights, privacy,
  duplicate state, transformations, quality, approval, classroom readiness, and
  reuse-planner inputs.
- Notion fields, Sheets rows, filenames, notes, prompts, comments, and display
  scores do not independently establish governed approval or compatibility.
- Search and reconcile by stable Asset ID and exact Drive identity; do not
  create duplicate records for the same canonical asset.
- Update working metadata only when the target and write authorization are
  explicit. Do not invent unknown governed values.
## Source Priority
When instructional sources overlap, prefer:
1. canonical unit or approved unit guide
2. current lesson plan, lesson brief, or teacher-authored current material
3. approved generation packet or teacher model
4. current working artifact being revised
5. templates and reusable support resources
6. archived or legacy material
7. attached files and memory snapshots

Prefer the designated live source. Do not write back a newer reality unless the
task requires it and write access is approved.
## Notion Retrieval Standard
When Notion is involved:
- Use dashboards and hubs for routing, not as the primary instructional source.
- Follow linked pages and database relations before broad searches.
- Use the underlying unit, lesson, packet, or asset record for content decisions.
- Prefer current and canonical records over templates, fragments, or archives.
- If two current sources are equally plausible and choosing wrong would change
  the work, ask one short clarification question.
## Navigation Registry Boundary
Do not hard-code dashboard names, database names, archive locations, or one-off
retrieval paths here. Those belong in a governed Navigation Registry or current
task context. A specifically named page, folder, database, or path remains the
retrieval target unless governance or write authorization conflicts.
## Google Drive Retrieval Rules
Use Drive when the task needs existing slide decks, worksheets, Docs, unit
guides, visual assets, or shared classroom files. Prefer current working files.
Update an existing canonical working file by default when revising the same
material; create a separate copy only when requested, protected, outside the
confirmed target workspace, or needed to preserve the original.
## Lightweight Curriculum Validation
Before governed classroom artifacts or implementation changes, confirm Notion
planning, Google Drive assets when relevant, GitHub change necessity, no
unreconciled new lesson direction, and documented source conflicts. If any item
cannot be confirmed, pause before final governed artifacts or implementation.
This checklist is not required for casual brainstorming or exploration.
## Version
0.1.6
## Changelog
- 0.1.6 aligned reusable-visual ownership with #785 and made Sheets
  review/reconciliation evidence rather than a competing canonical asset source.
- 0.1.5 keeps this standard under the repository line limit.
- 0.1.4 shortened this standard without changing source-order rules.
- 0.1.3 added Classroom Curriculum Source Order and lightweight validation.
- 0.1.2 added asset metadata rules for canonical visual asset tracking.
