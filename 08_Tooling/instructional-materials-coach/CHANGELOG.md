# Changelog

## Unreleased
- Tutorial-day connection for worksheets (#3215): lesson content specs may
  declare `prerequisite_tutorials` (tutorial ids); `tutorial_connection.py`
  resolves them against a typed tutorial registry (Tutorial 0: Adobe
  Express favorite-food reference setup — Text, Recommended fonts,
  Alignment and spacing, Export) and `compose_generation_context` projects
  the moves as context tokens plus a standard "tutorial connection"
  section naming the transfer moves with a catch-up pointer. Unknown
  tutorial ids fail closed; governed curriculum values win and are never
  duplicated.
- Main refresh for #3584 preserves slide-token location identity, rejects
   duplicate or invalid canonical slide indices and present null headings,
   and keeps worksheet preview imports free of provider transports.

- Governed lesson-content adapter (#3582): `lesson_content_result.py`
  consumes one #3580 `lesson-content` result (or its #2283 runner envelope)
  into the existing `LessonContent` via `with_context_tokens`, bound to an
  exact request, canonical unit, lesson number, and run provenance. Foreign
  unit, wrong lesson, malformed relation, unverified/stale source, run
  mismatch, widened authority, extra or credential-bearing keys, missing
  required fields, empty-string vocabulary, and authored-objective conflicts
  fail closed with explicit reason codes. Authored slides, questions, and
  title are preserved; absent Key Vocabulary stays absent; YAML-only
  behavior is unchanged. `worksheet_preview.py` and `imc-build
  preview-worksheet` add an enforceable offline no-write planned-worksheet
  preview receipt (`imc-lesson-worksheet-preview-v1`) that never requests
  credentials, builds Google clients, renders, or claims a native or
  classroom-ready artifact. See `docs/lesson-content-result-adapter.md`.
- Governed lesson-content adapter hardening (#3582, #3584 repair): the
  adapter and `preview-worksheet` CLI now fail closed on scalar authored
  fields, unhashable sources, zero-width required text, admission or
  envelope schema drift (admission exact-keyed, `gce_required` fail-closed),
  display-name mismatch, case/whitespace-variant lesson identities, deeply
  nested evidence, malformed slide structures, and unresolved
  `{{placeholder}}` governed text. Empty authored objectives are filled only
  under an independent authored `lesson_identity` binding exactly matching
  the selected lesson; whitespace-only optional source fields are absent,
  not malformed. The CLI byte bound applies to bytes actually read, and
  malformed/null/scalar YAML fails controlled as input-unreadable.
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