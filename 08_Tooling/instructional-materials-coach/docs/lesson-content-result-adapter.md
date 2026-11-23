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
Authored slide indices use the same positive integer identity as the existing
slide-token and location contracts. Numeric string indices are canonicalized
on a copied slide; invalid or duplicate canonical indices and present null
headings block both parsed content and direct adapter composition. Omitted
headings remain valid. The direct adapter also requires a visible authored
title. Main's slide-token helpers remain available.

Each rejection raises `LessonContentResultError` with a closed reason code:

| Condition | Reason code |
|---|---|
| Not a result/envelope, missing keys, bad types, evidence nested too deep | `result-malformed` |
| Extra key anywhere in result, source, authority, lesson, envelope, or admission | `result-unexpected-key` |
| Credential-class key carrying a non-boolean | `credential-key-present` |
| Wrong `result_kind`, `request_class`, or schema; envelope or admission schema drift; admission not an admitted lesson-content read | `result-class-mismatch` |
| Blocked/failed runner envelope, or wrong dispatch reason | `dispatch-not-completed` |
| Any widened authority or performed-write flag (result, envelope, or admission, including `gce_required`) | `authority-not-fail-closed` |
| Admission and result provenance (`request_id`, `repository`, `issue_number`, `generated_at`) disagree | `provenance-mismatch` |
| Source not admitted (unknown or unhashable `logical_source`, wrong catalog display name) | `source-unknown` |
| Source not `verified-current` (unverified, stale) | `source-unverified` |
| Source access is not `read-only` | `source-not-read-only` |
| Result repository is not the canonical repository | `repository-mismatch` |
| Request id differs from the binding | `request-mismatch` |
| Any lesson on a different canonical unit | `unit-mismatch` |
| Malformed relation, URL, or empty-string field; invisible (zero-width) required text; unresolved `{{placeholder}}` in governed lesson text | `lesson-malformed` |
| Whitespace-only optional fields (`daily_focus`, `key_vocabulary`) are producer-absent, not malformed | (normalized to absent) |
| Bound lesson absent / duplicated or case/whitespace-variant identity | `lesson-not-found` / `lesson-identity-ambiguous` |
| Required target, evidence, URL, or number absent | `lesson-field-missing` |
| Selection is not a trimmed, well-formed `LessonContentSelection` | `selection-malformed` |
| Authored objectives conflict with the verified lesson | `objective-conflict` |
| Authored objectives, slides, worksheet questions, or slide structures absent or malformed | `authored-content-missing` |
| Empty authored objectives without an independent authored lesson-identity binding matching the selected lesson | `authored-identity-missing` |
| Context token collides with existing evidence | `context-token-conflict` |

## Authored lesson-identity binding
Authored content may declare an independent lesson identity:

```yaml
lesson_identity:
  day_lesson_number: "Day 1"
```

The key is optional and, when present, must carry exactly `day_lesson_number`.
When the authored objectives are explicitly empty, the adapter fills them from
the verified target/focus only if this binding exactly matches the selected
lesson. The title is not canonical identity and is never the matching rule:
authored material whose title names the lesson but carries no binding is
refused with `authored-identity-missing` rather than silently adopting
another lesson's objectives.

## Composition
- Authored title, slides, and worksheet questions are preserved exactly.
  Notion supplies none, so composition requires them to be authored. Scalar
  (non-list) authored fields are malformed input, never character lists;
  malformed slide structures fail closed instead of raising mid-build.
- Authored objectives must contain the verified Daily Learning Target
  (whitespace-folded exact match) and must not contain another lesson's
  target or focus. An explicitly empty authored list is filled from the
  verified target and focus only under an independent authored
  lesson-identity binding that exactly matches the selected lesson (see
  above); without the binding the composition is refused.
- Governed lesson text carrying an unresolved `{{placeholder}}` is refused
  at the adapter, not just at preview time.
- Verified values are added through `LessonContent.with_context_tokens` as
  `context_lesson_*` tokens (target, focus, day, unit, source evidence,
  record URL, request id, run provenance, source verification state,
  objective source) plus the fixed-false authority tokens already used by
  `compose_generation_context`.
- Absent Key Vocabulary produces no token. A whitespace-only optional field
  is absent, not malformed. Nothing is defaulted or inferred.
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

