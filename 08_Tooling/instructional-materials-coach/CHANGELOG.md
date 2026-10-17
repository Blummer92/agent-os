# Changelog

## Unreleased

- Student-voice repair (#3213/#3644 R5): `student_voice.py` matching is
  now Unicode-normalized (NFKC) and casefolded with explicit zero-width
  separator, dash-variant, and soft-hyphen handling followed by
  word/token-boundary detection -- never bare substring matching.
  "Translate stage directions into a storyboard." and "Investigate rules"
  now pass; hyphen/Unicode-dash/zero-width/split-run evasions
  (``Heavy-modeling``, ``teacher\u200b model``) are caught. Explicit
  declarations are canonicalized exactly like scanned copy and stay
  bounded (known vocabulary, unique, at most 16). The pre-write screen
  (`require_student_voice`, via `compose_governed_build_request`'s new
  `doc_template_tokens` projection) scans only replacement values for
  tokens the worksheet Doc template actually carries -- an unused
  slide-only token can no longer block a Docs build, and no intended
  worksheet content is removed. Terminal QA rechecks the persisted
  rendered Docs text with the same vocabulary and declared exemptions
  (`qa-teacher-voice-in-worksheet`); the declarations are bound into the
  expectations hash so recovery cannot reuse QA across declaration sets.
- Production wiring for the student-voice screen (#3213/#3644):
  `build_request.compose_governed_build_request` now fails closed
  (`StudentVoiceError`) when the planned worksheet `replaceAllText` text
  carries teacher-guide modeling voice, before any `LiveBuildInput` is
  returned and before any Drive write. The single seam covers both `imc
  build` and scheduled consumers via `live_build_input_factory`. New
  `student_voice.require_student_voice` reuses the existing vocabulary and
  preserves the explicit-declaration escape hatch
  (`explicit_student_copy_teacher_voice_phrases`; unknown declarations fail
  closed).
- Student-voice filtering for student-facing worksheets (#3213):
  `student_voice.py` screens student copy for teacher-guide modeling voice
  (rigor-ramp stage labels, cognitive-load jargon, teacher-phrased
  gate/recovery rules, teacher modeling scripts) with whitespace-normalized
  case-insensitive substring matching; the student-material PDF preview
  fails closed on leaked teacher voice unless the caller explicitly
  declares a known phrase via
  `explicit_student_copy_teacher_voice_phrases`. Teacher guidance belongs
  in the teacher guide and slide deck, never on the student sheet.
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
