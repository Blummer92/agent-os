# Offline advisory draft evaluation (#4072)

## Purpose
`imc-build evaluate-draft` evaluates one lesson draft that a host session wrote.
It reports a closed vocabulary of deterministic findings in one content-safe
receipt, contract `imc-draft-evaluation-v1`. It is a leaf module
(`draft_evaluation.py`) that reuses the lesson-content adapter, the worksheet
preview, the student-voice scan and `normalize_text`. It performs no I/O of its
own; the CLI reads the bounded input files and writes only the receipt path it
is given.

## What a result does not say
The evaluator is deterministic and advisory. A `no-deterministic-finding` status
is a statement about the closed checks below and nothing else. It makes no claim
about writing, subject accuracy, grade level, student suitability or classroom
readiness. The receipt says so in fixed fields:

- `semantic_review` is always `not-performed`.
- `not_evaluated` always lists `audience-fit`, `factual-accuracy` and
  `instructional-completeness`, and also lists `structure-minimum` when neither
  `--min-questions` nor `--min-slides` was supplied and `revision-regression`
  when `--prior-draft` was not supplied, so an omitted optional input is visible
  in the receipt instead of silent.
- `audience_fidelity` is always `not-evaluated-deterministically`.
- `classroom_ready` is always `false` and `preview_only` is always `true`. The
  receipt grants no execution, external-write, production or publication
  authority, and only the existing D8 admission process can establish classroom
  readiness.

Every CLI line that states the status also states `semantic_review` and
`not_evaluated`. Nothing requires a host to run this command, and it does not
verify that any host did. CI cannot assert writing quality: the model-produced
fixtures prove that findings are reproduced, not that a draft is good.

## Command
```
imc-build evaluate-draft --content DRAFT.yaml
    [--prior-draft PRIOR.yaml]
    [--lesson-content-result RESULT.json --request-id ID --canonical-unit-page-id PAGE_ID --lesson "Day 1" --generated-at RUN:ATTEMPT]
    [--material-requirement REQUIREMENT.json] [--artifact-type TYPE]
    [--min-questions N] [--min-slides N] [--receipt-out RECEIPT.json]
```
Inputs are bounded to 262,144 bytes each (the existing
`MAX_LESSON_CONTENT_RESULT_BYTES`). Draft YAML additionally rejects aliases
(including alias chains) and structures deeper than 64 nodes or exceeding 8,192
composed nodes so small inputs cannot amplify into unbounded expanded content.
An unreadable, oversized or malformed input, an incomplete identity group, a
non-positive minimum or an invalid requirement is reported on stderr as
`input rejected (<reason>)`, exits 1, and writes no receipt. The evaluator
rejects an explicitly empty `--artifact-type`, and conflicting types from
`--artifact-type` and a supplied MaterialRequirement are rejected with
`artifact-type-conflict` instead of silently treating two supported types as
one. Without `--receipt-out` the receipt is printed to stdout. The status
line always goes to stderr.

To preserve supplied evidence, `--receipt-out` must not designate the same file
as `--content`, `--prior-draft`, `--lesson-content-result`, or
`--material-requirement` (including symlink and hardlink aliases). The CLI
rejects such an output as `input-output-path-collision` before writing.

Exit code 0 for `no-deterministic-finding` and `review`; exit code 1 for `fail`,
`blocked` and input errors, mirroring `preview-worksheet`.

## Identity modes
The five identity arguments are all-or-none.

- **Identity verified.** The existing `preview_lesson_worksheet` path runs. When
  it accepts the evidence, the receipt has `lesson_identity: verified`, a
  text-free projection of the preview receipt (`checks`, `planned_content_sha256`
  and identity ids; no question, slide or lesson text) and claim grounding from
  the verified lesson fields. When it blocks, the receipt status is `blocked` and
  `identity_reason_code` carries the adapter's closed reason code unchanged.
- **Identity not verified.** With no identity arguments the receipt has
  `lesson_identity: not-verified`, no preview, an empty grounding set, and only
  the identity-independent findings run. Verified identity exists today for one
  governed lesson-content request (Candy Branding). Other units can be evaluated
  only in this mode.

## Closed findings
Locations are the existing content-spec token names (`title`, `objective_<n>`,
`slide_<index>_heading`, `slide_<index>_bullet_<n>`, `question_<n>`) or one of
`slides`, `worksheet_questions`, `draft`. A finding never carries draft text.
Every finding carries a fixed one-line `remediation`; none tells the host to
delete the flagged item to clear a finding.

| Code | Severity | Condition |
|---|---|---|
| `draft-teacher-voice-in-student-copy` | fail | `scan_teacher_voice` matches a student-facing string |
| `draft-instruction-line-over-35-words` | manual-review | a worksheet question or slide bullet longer than 35 words (the rubric's advisory Quick QA heuristic "about 35 words") |
| `draft-ungrounded-claim-pattern` | manual-review | a match of one of four closed pattern families (percentages, multiplicative claims, attributions, absolute quantifiers) that is not a substring of the verified lesson fields after `normalize_text` and case folding; the grounding set is empty without verified identity |
| `draft-structure-below-request-declared-minimum` | fail | fewer substantive (nonblank) questions or slides than `--min-questions` or `--min-slides`; applies only when supplied, never defaulted, recorded as request-declared and unverified |
| `draft-revision-items-removed` | manual-review | with `--prior-draft`, fewer slides or fewer questions than the prior draft (counts only) |
| `draft-unchanged-since-prior-draft` | manual-review | with `--prior-draft`, the parsed draft equals the prior draft after `normalize_text` on every string |
| `draft-ai-generation-not-permitted` | blocked | a supplied MaterialRequirement has `ai_review.ai_assisted_generation_permitted` false |
| `draft-artifact-type-not-supported` | blocked | a declared artifact type is not `worksheet` or `slide-deck`; `teacher-guide` and `teacher-modeling-package` also carry a routing note to the Teacher Modeling Coach (#3562) |

`normalize_text` folds whitespace only. It applies no case folding, punctuation
stripping or fuzzy matching, so a change to case or punctuation is a change. The
unchanged-draft finding detects one unchanged resubmission. The comparison
uses student-facing title, objectives, slide indexes/headings/bullets, and
questions; changes only to lesson identity, context tokens or prerequisite
metadata do not falsely count as a revision. It is not a revision budget, a
stop rule or a progress check, and it does not say whether earlier findings were
resolved. A claim-pattern match is a review queue entry, not a
judgment of falsity: legitimate statistics are flagged unless the verified lesson
text contains them, and no input suppresses, defaults or downgrades a finding. An
absent MaterialRequirement is recorded as `requirements: absent` and is never
treated as permission.

## Status and receipt
`status` is derived in this order: `blocked` for any blocked finding or an
identity failure; otherwise `fail`; otherwise `review`; otherwise
`no-deterministic-finding`.

The receipt contains codes, counts, location tokens, SHA-256 hashes of the exact
bytes of each file input (draft, prior draft, lesson-content result,
MaterialRequirement) and fixed strings, so long, multi-line and non-ASCII drafts
never reach the canonical-JSON string limits. `receipt_fingerprint` is the
SHA-256 of `canonical_json_bytes` over the receipt without that field. The same
inputs always produce the same receipt and fingerprint; there are no timestamps
or paths.

## Installation note
The Coach declares Google client libraries, ReportLab and PyYAML as runtime
dependencies, and `instructional-workflow-contracts` (built from the repository's
`src/`) as an exact-bounded dependency. They must be installed even for this
offline command because the `imc-build` entry point imports them. The documented
supported installation is non-editable wheels (see the README release
checklist): build the `src/` distribution and the Coach distribution, install
both into a fresh environment, and run `imc-build` from outside the checkout.

## Not in scope
No model call, provider SDK, credential, network or subprocess; no drafter and no
revision engine; no readability or grade-level scoring; no rendering or layout;
no change to `build`, admission or any shared contract; no Notion, Drive or GitHub
write; no knowledge persistence. Host guidance for drafting, revision and
independent review is #4073.
