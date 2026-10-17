# Changelog

## Unreleased

- Placement transport revision identity (#3257, producer): the
  `placement_transport.py` seam now enforces artifact revision identity
  end to end. `_request_payload` refuses to build a request whose target
  carries no artifact revision id; `AppsScriptPlacementTransport`
  rejects the pre-repair synthetic `docs-child-<index>` element id (never
  a real persisted Docs inline object id) and requires the hardened
  reference's read-back post-placement revision evidence, failing closed
  otherwise. The `apps-script/VisualPlacementTransport.gs` REFERENCE
  (no deployment) now preserves/enforces `artifact_revision_id` in
  `validateRequest_` and its `place` returns the actual persisted Docs
  inline object id from a before/after read-back diff plus
  `requested_revision_id` / `post_placement_revision_id`. Node
  conformance suite
  `apps-script/test/visual-placement-transport.conformance.test.mjs`
  (7 checks: revision enforcement, real read-back id, revision evidence,
  fail-closed without a read-back surface); Python adapter suite
  `tests/test_3257_producer_revision_identity.py` (7 checks). The script
  deliberately does not enforce live-revision equality (sequential batch
  insertions legitimately advance the revision); batch continuity is
  enforced repository-side (#3258). Contract:
  `docs/visual-placement-contract.md`.
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
