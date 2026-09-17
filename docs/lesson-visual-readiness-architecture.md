# Lesson Visual Readiness — Architecture Investigation

Read-only investigation of the teacher lesson visual-readiness workflow, verified
against current `main` at commit `45fcae3` (2026-09-17). No GitHub issue/PR
mutation, no Notion/Drive/classroom write, no image generation, and no new
executable agent was performed or is proposed here.

This document corrects a prior investigation draft that classified most of this
workflow as unimplemented. Repository evidence contradicts that classification.

## Executive Decision

| Decision | Value |
| --- | --- |
| Overall status | Implemented backend; two narrow seams missing |
| Confidence | High (contract code + passing tests + issue state) |
| Smallest missing seam | An `ImageGapBrief` → `ImageIntent` adapter that preserves `brief_id` |
| Second missing seam | Lesson-level aggregation of per-material cohesive plans |
| Recommended direction | Compose existing contracts; add one adapter. Do not create a readiness engine, prompt engine, asset library, or intake pipeline |

The prior draft's central premise — that visual-need planning, candidate
filtering, cohesive selection, gap briefs, prompts, and returned-image intake are
"specified but not implemented" — is false against current `main`. All are
implemented and green. The genuine gap is narrower and different in kind: the
implemented halves are not connected to each other.

## Preflight (AGENTS.md step 4)

The bounded CKR6 coding-lessons preflight was executed, not asserted:

```text
plan.retrieval_required     = True
plan.recommended_escalation = filtered-data-source-query
status                      = insufficient  (no-relevant-candidate, zero candidates)
source_authority            = advisory-only
```

Executed via `agent_memory_context_manager.lesson_preflight.consume_lesson_preflight`.
No Notion lesson candidates were supplied, so selection returned
`no-relevant-candidate`. GitHub remained authoritative throughout; lessons are
advisory-only and none were consumed. This is a recorded bounded outcome, not a
blocker.

## Corrected Capability Map

Every row below was verified by reading the implementation and running its tests.

| Capability | Issue | Actual status | Evidence |
| --- | --- | --- | --- |
| Visual need determination | #847 | **Implemented** (closed/completed) | `src/instructional_workflow_contracts/visual_needs.py:48` `plan_visual_needs` |
| MaterialRequirement visual direction | #850 | **Implemented** | `material_requirement.py:160`; `V2_TOP_LEVEL_FIELDS` adds `visual_direction` |
| Approved candidate filtering | #849 | **Implemented** (closed/completed) | `visual_asset_candidates.py:40` `filter_approved_visual_candidates` |
| Cohesion evidence | #871 | **Implemented** (closed/completed) | `visual_asset_compatibility.py` |
| Cohesive set selection | #851 | **Implemented** (closed/completed, PR #927) | `cohesive_visual_plan.py:48` `plan_cohesive_visual_set` |
| Missing-role detection | #851 | **Implemented** | `cohesive_visual_plan.py:236` `unfilled_required_roles` |
| Image-gap briefs | #851 | **Implemented, but semantically empty** | `cohesive_visual_plan.py:638` `_gap_brief` — see below |
| Provider-neutral prompt contract | — | **Implemented** | `image_intent.py` `validate_image_intent`; `assemble_gemini_manual_prompt:199` |
| Returned-image provenance contract | — | **Implemented** | `image_intent.py` `validate_imported_asset_context` (`source_mode`, `provider_claim`, `prompt_claim`) |
| Image intake + dedup | #952/#953 | **Implemented** | `08_Tooling/visual-asset-intake/` |
| Routing + teacher confirmation | #957/#1025/#1026 | **Implemented** | `08_Tooling/visual-asset-routing/` (`Add \| Change \| Skip`) |
| Drive persistence + verified readback | #958 | **Implemented** (offline-first) | `08_Tooling/visual-asset-drive-writer/` |
| Visual Asset Library reconciliation | #959 | **Implemented** (offline-first) | `08_Tooling/visual-asset-notion-writer/` |
| IMC runtime gate on gaps | #944 | **Implemented** (closed/completed) | `instructional_materials_coach/visual_reuse.py`, `cli.py:115` |
| Teacher-facing PDF rendering | #1417 | **Implemented** | `instructional_materials_coach/teacher_reference_pdf.py` `render_teacher_reference_pdf` |
| Writer coordination | #954 | **Not implemented** | Referenced as "later" in two READMEs; no package exists |
| Gap-brief → prompt adapter | — | **Missing** | See "The Real Gap" |
| Lesson-level readiness aggregation | — | **Missing** | See "The Real Gap" |

Validation run for the contract layer:

```text
PYTHONPATH=src pytest tests/test_cohesive_visual_plan.py \
  tests/test_image_intent_contract.py tests/test_visual_asset_candidates.py \
  tests/test_picture_perfect_integration.py tests/test_visual_needs_plan.py \
  tests/test_visual_asset_picker.py tests/test_issue_2385_*.py tests/test_issue_2386_*.py
→ 84 passed
```

## The Real Gap

### 1. Gap identity dead-ends

`cohesive_visual_plan.py:650` mints a `brief_id` and `missing_visual_role_id`.
A repository-wide search shows these are **produced and never consumed**: the
only non-test references are the three lines that create them. The single
downstream consumer of `image_gap_briefs` is the Instructional Materials Coach,
which uses them solely as a blocking count (`cli.py:115`, `visual-gap-blocked`).

Neither downstream contract can carry the identity back:

- `ImageIntent.identity` = `{contract_version, intent_id, asset_id, concept, purpose}`
- `ImageIntent.library_handoff` = `{unit_lesson, asset_role, intended_reuse, candidate_status, review_notes}`
- `ImportedAssetContext` = `{..., source_mode, provider_claim, prompt_claim, model_claim, generated_at_claim, original_filename, source_note}`

None has a gap/brief reference field. So a returned image cannot be bound back to
the gap that requested it. This — not a missing intake pipeline — is the actual
break in the closed loop.

### 2. Gap briefs cannot produce a usable prompt

`_gap_brief` hardcodes every art-direction field to `"unspecified"`:
`required_visual_style_family`, `composition`, `perspective`, `palette`,
`line_treatment`, `shading_treatment`, `background_requirement`, and
`dimensions_or_aspect_ratio`. `subject_or_concept` is just `role["role_type"]`.
`tests/test_cohesive_visual_plan.py:216` asserts this is intended behavior.

This is faithful to #851, which requires an explicit bounded `unspecified`
representation rather than invented detail. But `validate_image_intent` requires
non-empty `composition`, `viewpoint`, `look`, and a non-empty `must_show` list.
**A gap brief therefore cannot currently be converted into a valid ImageIntent**
without new governed evidence. The adapter is not a formatting exercise; it needs
a source for those fields.

`build_image_intent` in `picture_perfect_integration.py:222` is not a precedent to
copy — it unconditionally raises, deliberately refusing generative reconstruction
of software-tutorial UI.

### 3. Aggregation is per-material, not per-lesson

`plan_visual_needs` and `plan_cohesive_visual_set` operate on **one**
`MaterialRequirement`. A lesson with several materials produces several
independent cohesive plans with no combining contract.

However, `MaterialRequirement.IDENTITY_FIELDS` already carries `course_ref`,
`unit_ref`, and `lesson_ref` (`material_requirement.py:75`), and these propagate
through `source_requirement` into every downstream record. Lesson-level readiness
is therefore **reachable by direct composition** — group validated plans by
`lesson_ref` — without a new persistent projection.

## Consequences for the Proposed Design

### TeacherLessonView should probably not be built

#2225 (open, `status:needs-decision`) states its own precondition: define
`DeveloperMissionView` or `TeacherLessonView` **"only when direct composition is
proven insufficient"**, and keep any view non-authorizing and non-persistent.
Because `lesson_ref` already threads through the contracts, direct composition
appears sufficient. Recommending a TeacherLessonView section presumes the view
that #2225 has not yet decided to create, and inverts its test.

### "Available" must mean materialized, not selected

The most recent governing change on this workflow is #2334 (merged `a8cca5a`,
2026-09-17), which raised `artifact-first-response-standard.md` to 0.1.3:

> Asset metadata is not artifact fulfillment. An asset ID, eligible-asset ID,
> selection decision, or successful metadata read does not prove that image bytes
> or another usable source reference were recovered, materialized, embedded, or
> placed. Completion evidence must distinguish discovery, selection,
> materialization, and placement.

A readiness view reporting "available: 4" from selection evidence alone would
violate this standard. Any readiness projection must carry the four states
separately. The prior draft predates and omits this constraint.

### A teacher-facing PDF already exists

`render_teacher_reference_pdf` renders bounded teacher references and takes
caller-supplied asset bytes only — it performs no retrieval and makes no
selection or approval decision. The teacher/student boundary is already drawn
against `student_material_pdf.py`. Extend this renderer; do not design a new
planning-export type.

### The intake questions are already answered in-repo

Two questions the prior draft escalated to Zachary have current repository
answers:

- **Teacher confirmation UX**: `visual-asset-routing` defines `Add | Change | Skip`,
  with duplicates routing to `Use Existing | Review` and near-duplicates to
  `Use Existing | Keep New | Review`.
- **Approval before reuse**: `visual_asset_picker.py:134` already defaults
  `source_preference="reuse-first"` and `generation_allowed=False`.

### #1049/#1776 overlap is confirmed absent

`test_issue_2385_image_prompt_activity_contract.py` classifies *student activity
types* ("image-prompt-writing" vs "tool-operation"). It is unrelated to teacher
prompt projection. No competing prompt system needs importing.

## Blocking Dependency

Live readiness computation depends on reading the Visual Asset Library, which is
currently **fail-closed**. Per #2283 (open, `status:needs-decision`): the
executable catalog still holds `null` source/page ids with
`verification_state=unverified`, the direct Notion plugin is blocked by the
workspace administrator, and activation requires a capable configuration operator
to set `NOTION_TOKEN`, share the two sources, and re-verify identities.

Notably, the authorized #2283 smoke test is **Photography Foundations** — the same
fixture this workflow targets. Offline contract work can proceed; anything
requiring live approved-asset evidence cannot until #2283 activates.

## Recommended Sequence

| Order | Work | Owner | Blocked by |
| --- | --- | --- | --- |
| 1 | Resolve #868 (open, `status:ready`): prove whether current contracts already supply asset-level compatibility evidence, or add the smallest extension. Its "Blocked consumer: #849" framing is stale — #849 and #871 have shipped | Instructional Materials Coach | none |
| 2 | Decide the governed source for gap-brief art direction (`composition`, `palette`, `perspective`, …), since #851 forbids inventing it | Instructional Materials Coach | 1 |
| 3 | Add the `ImageGapBrief` → `ImageIntent` adapter carrying `brief_id` through `library_handoff` | Instructional Materials Coach | 2 |
| 4 | Add a gap reference to `ImportedAssetContext` so returned images bind to their brief | Integration Manager | 3 |
| 5 | Compose lesson-level readiness by grouping plans on `lesson_ref`; report discovery/selection/materialization/placement separately per #2334 | ChatGPT Orchestrator (composition) | 3 |
| 6 | Extend `render_teacher_reference_pdf` with a readiness section | Instructional Materials Coach | 5 |
| 7 | Revisit #2225 only if steps 5–6 prove direct composition insufficient | #2225 owner | 5, 6 |
| 8 | #954 writer coordination, if intake volume justifies it | Google Workspace Automation Engineer | #2283 |

## Issue Reconciliation

| Issue | State | Recommendation |
| --- | --- | --- |
| #785 | closed/completed | Architecture ratified; its 5-issue split is fully delivered. No change |
| #847, #849, #851, #871, #944 | closed/completed | Do not reopen. Consume as implemented contracts |
| #868 | **open, `status:ready`** | The correct existing home for steps 1–2. Refresh its stale "Blocked consumer: #849" line |
| #2225 | open, `status:needs-decision` | Do **not** add a Visual Readiness section yet. Supply the composition evidence its precondition asks for |
| #2283 | open, `status:needs-decision` | Hard dependency for live readiness. No change proposed |
| #2334 | merged `a8cca5a` | Binding constraint on readiness semantics |
| New issue | — | **Not recommended.** #868 covers the compatibility evidence; the adapter is a focused child of the #851/#944 lineage |

## Open Question for Zachary

One question has no repository answer and materially changes step 2:

**Where should gap-brief art direction come from?** #851 forbids inventing it and
requires `unspecified`. Options: (a) extend `MaterialRequirement.visual_direction`
to carry per-role direction; (b) derive it from the already-selected cohesive set
so a new asset matches assets in the same lesson; (c) have the teacher supply it
at prompt time. Option (b) reuses existing evidence and directly serves cohesion,
which is the stated purpose of the gap brief, and is the recommended default.

## Report

- **Files changed**: this document only.
- **Tests run**: 84 passed across the eight focused visual/contract suites listed
  above; CKR6 preflight executed against `agent_memory_context_manager`.
- **Docs updated**: this document.
- **Unresolved blockers**: #2283 Notion read path is fail-closed pending an
  external configuration operator; the governed source for gap-brief art
  direction is undecided.
- **Handoff**: Instructional Materials Coach owns steps 1–3 and 6; Integration
  Manager owns step 4; #2225 owner decides step 7.
- **Remaining risks**: a readiness projection could report selection as
  availability, violating the 0.1.3 standard; an adapter that fills `unspecified`
  brief fields with defaults would violate #851's no-invention rule; building
  TeacherLessonView before testing direct composition would inflate scope against
  #2225's own precondition.
- **Authorization boundary**: read-only. No merge, issue closure, workflow,
  credential, production, or external-system write was performed or is authorized
  by this document.
