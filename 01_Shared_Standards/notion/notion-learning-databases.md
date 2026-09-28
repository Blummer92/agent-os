# Notion Learning Databases

- Use bug log for bugs, pattern library for reusable patterns, lessons database for durable but scoped lessons.

## Lessons Learned Database Fields

Reference schema for the live "Lessons Learned" database (Curriculum
Operations Hub), so agents don't need to re-fetch it from Notion each
time. Confirm the live schema before writing if it may have changed.

- `Lesson ID` (unique ID / auto-increment) — stable logical identity; CKR11
  lesson activation uses this, never the Notion page URL, as `lesson_id`.
  Query it with a `unique_id` number filter.
- `Lesson Learned` (title) — short summary.
- `Status` (select) — `New | Applied | Needs follow-up | Archived note`.
  Present on the live data source; do not assume it is absent. Query it with a
  `select` filter; a `status` filter is rejected with HTTP 400 (#3032).
- `Owner / Agent` (text) — which agent/tool produced this.
- `What Happened` (text)
- `What To Do Next Time` (text)
- `Guardrail` (text)
- `Severity` (select) — Low, Medium, High, Critical.
- `Learning Type` (select) — Mistake, QA feedback, Testing lesson,
  Deployment lesson, Scope/permission lesson, Trigger lesson.
- `Area` (select) — Curriculum, Automation, Dashboard, Governance,
  Documentation, Testing.
- `Applies To` (multi-select) — Apps Script, Google Workspace, Drive,
  Notion, Curriculum, Dashboard, Deployment, Instructional Materials.
- `Source Type` (select) — Task, ADR, Incident, Reflection, Manual.
- `Source Link` (url)
- `Follow-up Needed?` (checkbox)
- `Surface Before Work?` (checkbox)
- `Related Task`, `Related Automation` (relations) — set only if a
  matching record already exists; do not create one just to link it.

## Version
0.1.3

## Changelog
- 0.1.3 pins the live-verified `Lesson ID` (unique ID) and `Status` (select)
  property types and their query filter types (#3032).
