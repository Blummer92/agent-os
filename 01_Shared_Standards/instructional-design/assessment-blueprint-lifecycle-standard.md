# Assessment Blueprint Lifecycle Standard
## Purpose
Define the reusable, provider-neutral lifecycle layer for the #838 Assessment Blueprint Core. This layer owns version transition evidence, change-impact classification, stale-validation detection, bounded invalidation, and revalidation scope without redefining assessment-design or blueprint-core semantics.

## Ownership Boundary
The lifecycle consumes one exact `assessment-blueprint-core/v1` object. #837 owns assessment-design meaning and #838 owns blueprint-core structure and validation. This standard may classify the effect of a change; it must not rewrite purpose, targets, claims, evidence, methods, scoring meaning, accessibility meaning, AI policy, provenance, or fixed authority.

## Lifecycle Evidence
Every projection binds the stable `blueprint_id`, current `blueprint_version`, `last_validated_blueprint_version`, current and last-validated source versions, current and last-validated upstream design-record IDs, canonical changed paths, dependency-impact state, affected object IDs, and downstream consumers affected by changed handoff fields. Inputs are caller-supplied structured evidence; this contract performs no live lookup or external write.

## Deterministic Change-Impact Classes
Return exactly one primary class using this precedence, highest first: `downstream_invalidation`, `teacher_review`, `qa_rerun`, `blueprint_validation`, `local_validation`, `no_revalidation`.

- `no_revalidation`: non-semantic metadata only; no identity, source, authority, core semantic, or handed-off field changes.
- `local_validation`: bounded non-semantic wording or presentation clarification that changes no upstream meaning or downstream contract.
- `blueprint_validation`: a core planning object changes, including provenance, task format, complexity, blockers, uncertainties, or other blueprint semantics not owned by a stronger class.
- `qa_rerun`: evidence sufficiency, method alignment, scoring validity, accessibility, AI-policy consistency, authority validation, or downstream-schema completeness changes.
- `teacher_review`: an authorized teacher decision changes purpose, intended use, available time, scoring/observation approach, authentic-task feasibility, or bounded assignment conditions.
- `downstream_invalidation`: a field already handed to sequencing, QA, dashboard, or portability consumers changes, or a shared semantic root changes.

Unknown change paths or ambiguous dependency impact fail closed to `needs-decision`; they are never classified as safe.

## Stale Validation
`stale_validation` is true when any of these are true: current blueprint version differs from the last validated version; authoritative source version differs from the validated source version; upstream design-record identity changed; a handed-off field changed; a shared semantic root changed; or dependency impact is ambiguous. Emit bounded stale reason codes for every true condition.

A metadata-only change may remain current only when it does not advance semantic identity or any validated source/handed-off field. A stale result cannot be presented as current merely because the underlying assessment content still appears usable.

## Bounded Invalidation
When a local object changes, invalidate only that object and dependent validations. Preserve unrelated object IDs explicitly. A local edit must not cause global invalidation.

For downstream consumers, invalidate only consumers whose handed-off fields changed. Current consumer roles are `sequencing` (#839), `qa` (#841), `dashboard` (#843), and `portability` (#846). If a shared semantic root changes, all dependent consumers may be invalidated. Ambiguous dependency impact fails closed instead of guessing a smaller set.

## Revalidation Scope
`required_revalidation_scopes` may contain subordinate checks in deterministic order: local validation, blueprint validation, QA rerun, teacher review, and downstream invalidation. The primary class is the strongest required scope; weaker required scopes remain visible rather than being discarded.

Successful revalidation updates the corresponding last-validated identities only after the required scope passes. This lifecycle contract does not itself authorize or execute QA, teacher approval, classroom use, grading, production, publication, or external writes.

## Authority
Authority remains owned by the embedded #838 core object. The lifecycle schema references the #838 core schema rather than duplicating its authority object. Any attempt to add a lifecycle authority override, semantic override, or replacement assessment-design field is invalid.

## Synthetic Fixtures
Lifecycle fixtures are synthetic change observations. They must cover all six classes, source and upstream drift, bounded preservation, single-consumer invalidation, shared-root invalidation, and fail-closed negative cases for stale-as-current, global invalidation after a local edit, missed downstream invalidation, ambiguous dependency impact, authority override, and semantic reinterpretation.

## Non-Goals
No assessment generation, sequencing implementation, dashboard UI, recommendation engine, independent QA engine, persistence, Scheduler behavior, Notion/Drive write, grading/readiness mutation, accommodation or AI-policy change, new agent, workflow change, credential change, production effect, or external write.

## Version
0.1.0
