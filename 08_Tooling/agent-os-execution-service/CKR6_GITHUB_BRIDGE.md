# Finite GitHub CKR6 Bridge (#2851)

Issue #2851 adds the separately authorized GitHub-hosted Actions ingress in `.github/workflows/agent-os-ckr6.yml`. The comment form is `/agent-os ckr6 <json-object>`; `ckr6_github_bridge.py` strictly validates the bounded issue-start or failed-repair envelope, then delegates materiality to the existing CKR6 `plan_lesson_preflight` owner. A not-needed request reaches zero Lessons Learned provider reads. Only a request the existing CKR6 plan marks retrieval-required enters the step that exposes the existing `NOTION_TOKEN` and the live-verified repository variable `AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID`. The bridge never guesses that source identity, never routes through GCE, and publishes only bounded sanitized CKR6 result evidence. It creates no merge, closure, GitHub-write, Notion-write, or execution authority.

## Result postback (#2851 result-consumption seam)

The step summary and artifact are not readable through the ChatGPT host's GitHub
MCP surface, so the workflow posts the bounded CKR6 result back to the
originating issue as a machine-readable comment. The comment form is the marker
`<!-- agent-os-ckr6-result:v1 -->` followed by one line of canonical compact JSON
(`ckr6_github_bridge.serialize_ckr6_result_comment`); it never starts with
`/agent-os ckr6` and therefore cannot retrigger the ingress. The payload carries
the existing bounded result fields plus the issue-start `handoff_projection`
(the host's consumable context-packet unit) and the requesting comment id for
correlation. When `result.json` is absent, an explicit `manual-review` fallback
is posted instead of silence. The `execute` job holds `issues: write` for this
single postback; no other GitHub write is performed and no authority is created.

## Activation completeness

A merged/callable transport is not evidence that the retrieval-required CKR6 path is usable. Activation evidence for that path must prove the existing live-verified `AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID` binding is present and that a finite retrieval-required canary reaches bounded CKR6 result evidence. When the binding is absent or still pending, report `activation incomplete / binding pending`; do not project the retrieval path as usable and do not guess a source identity. This reuses #2854 as the binding owner and adds no second reader, registry, source store, or binding mechanism.

## Learning-loop operations (#3418)

The same ingress connects the existing, previously caller-less learning seams.
No workflow change, Notion write, store or authority is added.

- CKR6 `issue-start` and `failed-repair` results carry `selected_lessons`
  (`lesson_id`, exact `source_revision`, selection reasons), real
  `rejected_candidate_provenance`, and `materiality_source`
  (`caller-asserted-*` or `inferred-*`). The #2780 materiality default is
  unchanged, but an inferred not-needed is labelled as inferred and appears in
  the handoff `known_facts`.
- `lesson-candidate` (zero reads): `{"candidate": <CI/review outcome>}` runs
  `ci_review_learning.normalize_learning_outcome` (materiality/noise gate) ->
  CKR5 `evaluate_coding_failure` (identity/recurrence) -> CKR6
  `project_lesson_to_notion` and returns an authority-false `lesson_proposal`
  with a reviewable #3417 `catalog_entry_draft`.
- `lesson-refinement` (one known-ID read): `{"refinement": {lesson_id,
  source_revision, receipt_refs, evidence}}` reads exactly that lesson through
  the existing read-only route, refuses a stale revision, runs CKR7
  `evaluate_lesson_enrichment`, and returns a `revision_proposal` whose
  `catalog_entry_draft` targets the Lesson ID with the bound revision.
  At least one receipt comment URL is required.
- Receipts (`lesson_learning_loop`): `<!-- agent-os-lesson-receipt:v1 -->` +
  canonical JSON. Valid only when the referenced CKR6 result returned that
  exact lesson revision; applied/skipped use finite reasons; duplicates collapse
  by `(result comment, lesson, revision, task)`.
- Metrics (`lesson_learning_metrics`): read-only derivation from these
  comments: results, materiality source, retrievals, rejections, eligibility
  blocks, selections, valid/invalid/duplicate/conflicting receipts,
  selected-without-receipt, candidates, recurrences, refinement proposals and
  signals, and CKR12 accountability (matched by lesson number because the CKR12
  snapshot uses `lesson-N` while live IDs are `LL-N`). No causality is inferred.
