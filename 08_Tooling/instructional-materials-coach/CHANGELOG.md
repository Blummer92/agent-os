# Changelog

## Unreleased

- Worksheet heading keep-with-next (#3416): the canonical worksheet build
  sets `keepWithNext` on every heading paragraph (`HEADING_1`–`HEADING_6`,
  body and table cells) whose effective value is not already true, in one
  revision-bound `updateParagraphStyle` batch after text requests and before
  #3257 placement; nothing is written when no heading needs it. Terminal QA
  verifies the rule on the persisted readback (`layout-rule-violated` /
  `qa-heading-keep-with-next-missing`), and the QA evidence contract is now
  `terminal-qa-evidence-v2` so pre-rule verified evidence is never
  recovered. Shared pure resolver: `worksheet_pagination.py`.
- Terminal artifact-content QA (#3258): `artifact_content_qa.py` proves the
  persisted final artifact contains the governed required content and
  visuals, attributable to the current build and artifact state.
  `LiveBuildReceipt.succeeded` (the single completion owner) now requires
  both artifacts terminal-QA `verified`; metadata-only verification yields
  `persisted`, never `final`. Expectations derive from the planned
  `replaceAllText` requests and the #3257 visual bindings; evaluation reads
  back persisted Docs/Slides bodies (unresolved-token scan, content
  presence with whitespace-only normalization, visual marker/element
  observation, receipt-to-artifact revision binding, build-attribution
  checks). The existing `worksheet_revision_qa` / `visual_completeness`
  contracts are wired into the visual dimension. QA runs read-only on every
  terminal attempt including the resume fast path; verified evidence
  persists per idempotency key and is recovered only while artifact revision
  and expectations still match. 20-scenario regression matrix plus a
  red/green proof that the pre-repair base reported final with an
  unresolved token persisted. Canonical contract:
  `docs/terminal-qa-contract.md`.
- Worksheet revision QA (#2890): `worksheet_revision_qa.py` binds required
  visual roles across revisions so a vocabulary/content/layout fix cannot
  silently drop visual scaffolds and still pass as complete; render evidence
  with zero/missing required icons fails via the existing visual-completeness
  contract. `worksheet_layout_qa.py` flags large blank regions as accidental
  dead space only when expected content/response/visual roles are missing on
  the same page, routing intentional whitespace to manual review. The student
  PDF preview renderer now rejects internal review/workflow language
  (`PDF DRAFT`, `review before Google Drive`, production-authorization,
  routing, backend-handoff phrasing) from student-facing copy unless
  explicitly declared student copy, and provenance moved from a rendered
  footer paragraph into the PDF document properties.

## 0.2.0

- Added a Notion learning loop: `build` now writes a local lesson-candidate
  record to `reports/lessons/` on failure instead of failing silently, and
  a new `log-lesson` subcommand records manual entries (e.g. QA feedback).
  Records mirror the real Lessons Learned Notion database schema
  field-for-field but are never written to Notion automatically -- a human
  applies them using the mapping table in README.md. CLI restructured
  into `build`/`log-lesson` subcommands.

## 0.1.0

- Initial release: build a Slides deck and Docs worksheet from an
  approved template pair and a lesson content YAML, via Drive
  `files.copy` plus Slides/Docs `batchUpdate` `replaceAllText`.
