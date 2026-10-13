# Lesson-content result adapter and offline worksheet preview (#3582)

## Purpose
Connect one governed `lesson-content` result from the #2283/#3580 Notion read
path to the existing Coach `LessonContent` seam, and preview the resulting
worksheet content offline. This is an adapter, not a reader, curriculum
engine, schema, registry, or scheduler.

## Input contract
`lesson_content_result.py` accepts exactly the public result published by
`project_lesson_content_result` (`agent-os-notion-lesson-content-result`,
schema `1.0`), or the #2283 runner evidence envelope that wraps it. The
seven governed lesson fields are unchanged: `daily_learning_target`,
`daily_focus`, `key_vocabulary`, `canonical_unit`, `source_evidence`,
`day_lesson_number`, `record_url`. The root test
`tests/test_3582_lesson_content_imc_contract.py` pins the adapter's copy of
this contract to the producer's constants.

The caller binds the exact lesson with `LessonContentSelection`: request id,
dashed canonical-unit page id, `Day / Lesson Number`, and the result's run
provenance (`generated_at`, `<run_id>:<attempt>`). Every field must match.

## Fail-closed rules
Each rejection raises `LessonContentResultError` with a closed reason code:

| Condition | Reason code |
|---|---|
| Not a result/envelope, missing keys, bad types | `result-malformed` |
| Extra key anywhere in result, source, authority, lesson | `result-unexpected-key` |
| Credential-class key carrying a non-boolean | `credential-key-present` |
| Wrong `result_kind`, `request_class`, or schema | `result-class-mismatch` |
| Blocked/failed runner envelope | `dispatch-not-completed` |
| Any widened authority or performed-write flag | `authority-not-fail-closed` |
| Source not admitted for lesson content | `source-unknown` |
| Source not `verified-current` (unverified, stale) | `source-unverified` |
| Request id or run provenance differs from the binding | `request-mismatch` / `provenance-mismatch` |
| Any lesson on a different canonical unit | `unit-mismatch` |
| Malformed relation, URL, or empty-string field | `lesson-malformed` |
| Bound lesson absent / duplicated identity | `lesson-not-found` / `lesson-identity-ambiguous` |
| Required target, evidence, URL, or number absent | `lesson-field-missing` |
| Authored objectives conflict with the verified lesson | `objective-conflict` |
| Authored slides or worksheet questions absent | `authored-content-missing` |
| Context token collides with existing evidence | `context-token-conflict` |

## Composition
- Authored title, slides, and worksheet questions are preserved exactly.
  Notion supplies none, so composition requires them to be authored.
- Authored objectives must contain the verified Daily Learning Target
  (whitespace-folded exact match) and must not contain another lesson's
  target or focus. Only an explicitly empty authored list (`objectives: []`)
  is filled, and only with the verified target and focus.
- Verified values are added through `LessonContent.with_context_tokens` as
  `context_lesson_*` tokens (target, focus, day, unit, source evidence,
  record URL, request id, run provenance, source verification state,
  objective source) plus the fixed-false authority tokens already used by
  `compose_generation_context`.
- Absent Key Vocabulary produces no token. Nothing is defaulted or inferred.
- Without a lesson-content result, YAML-only behavior is unchanged.

## Offline no-write worksheet preview
`worksheet_preview.preview_lesson_worksheet` and
`imc-build preview-worksheet` compose the authored YAML with one verified
lesson, plan the worksheet with the existing `build_docs_replace_requests`,
and return an `imc-lesson-worksheet-preview-v1` receipt. The receipt is a
planned-content preview: `rendered=false`, `native_artifact=null`,
`classroom_ready=false`, all side-effect and authority flags false. It
reports deterministic checks (authored questions/slides/title preserved,
verified target and focus planned, vocabulary absent when unsourced, no
unresolved `{{tokens}}`); any failed check blocks the preview.

The preview path needs no `ALLOW_WRITE`, never requests credentials, never
builds a Drive/Docs/Slides client, never runs the live builder, and writes
no lesson record. Its modules import no provider or write module; tests
prove this transitively. Connected builds keep their MaterialRequirement,
current-curriculum, terminal-QA, and admission gates unchanged. The #3377
Scheduler dry-run remains an inert command-plan validator and is not
duplicated or replaced.

    imc-build preview-worksheet \
      --content <authored_lesson.yaml> \
      --lesson-content-result <result-or-evidence.json> \
      --request-id candy-branding-lesson-content \
      --canonical-unit-page-id 3907ac78-3131-8132-8f84-f9fd633acba5 \
      --lesson "Day 1" \
      --generated-at 38462963519:1 \
      --preview-out preview.json

## Not in scope
No rendered Docs/PDF preview, native artifact identity, slide preview,
teacher-modeling or worked-example alignment, cross-artifact instructional
QA, teacher rehearsal, MaterialRequirement reconciliation with Notion unit
identity, or Notion/Drive write. Each needs separate admission and evidence.
