# Changelog

## Unreleased
- Main refresh for #3584 preserves slide-token location identity, rejects
   duplicate or invalid canonical slide indices and present null headings,
   and keeps worksheet preview imports free of provider transports.

- Required Docs visual coverage repair (#3212): each declared worksheet
  figure is now a required Docs target with a distinct `(role_id, slot_id)`.
  `required_visual_example_bindings` fails closed on duplicate same-slot
  declarations across independent sections (naming both sections); approved
  reuse of one asset across *distinct* slots still passes.
  `require_visual_example_plan_coverage` now consumes
  `(role_id, slot_id, asset_id, required)` plan quadruples and rejects
  declarations covered only by *optional* plan assignments — an optional
  binding that is never placed cannot discharge a required worksheet figure.
  `compose_governed_build_request` accepts `worksheet_visual_targets` and
  binds each declared figure into `TerminalQAExpectations` as a docs-scoped
  `VisualExpectation` (`artifact_type="docs"`, part of `expectations_hash`);
  `_evaluate_visuals` fails closed with `qa-visual-wrong-artifact` when a
  required Docs figure has verified receipts only in other artifacts, so a
  Slides receipt can no longer satisfy a required Docs image obligation.
  Declarations merge into the existing placement expectations — no second
  completeness validator. Lessons declaring no visual examples keep the
  legacy artifact-agnostic behavior unchanged.
- Visual-example requirements for worksheets (#3212): lesson content specs
  may declare `visual_examples` (section, role_id, slot_id, caption) — the
  unit's per-section image needs (worked examples, before/after frames,
  clear-vs-confusing comparisons) as build-time obligations. Every declared
  example must be covered by the governed #944 visual plan before
  generation (`compose_generation_context` fails closed), so a worksheet
  whose unit requires visual examples can never be generated text-only.
  Declared captions project as `visual_example_{i}_caption` placeholder
  tokens for figure labels; coverage evaluation reuses the
  `visual_completeness` contract via `worksheet_visual_examples.py`.
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
