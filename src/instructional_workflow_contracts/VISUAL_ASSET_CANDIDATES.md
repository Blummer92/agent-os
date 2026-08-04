# Visual Asset Candidate Filtering

`filter_approved_visual_candidates(visual_needs_plan, candidates, *, source_revision)` is the pure Module B boundary for issue #849.

## Inputs

- `visual_needs_plan` must be validated `curriculum-visual-needs-plan-v1` evidence with the exact `visuals-required` outcome.
- `candidates` must be a built-in list containing no more than 32 compatibility envelopes accepted by `validate_visual_asset_compatibility_evidence`.
- `source_revision` is required bounded source-snapshot identity supplied by the caller. It is carried into candidate-set identity so movement in the source snapshot changes the result ID and fingerprint.

Plain plan mappings are not trusted. A `no-visual-needed` or `manual-review-required` plan is not actionable and fails closed.

## Filtering behavior

Each candidate is revalidated independently and placed into exactly one deterministic group:

- `eligible`: compatibility evidence is eligible and overlaps a governed plan role, approved material type, and compatible orientation;
- `rejected`: evidence is invalid, hard-rejected by Module A, or mismatches the plan role, material type, or orientation;
- `manual_review`: Module A determines that bounded human review is required.

Input order does not affect group ordering, candidate-set identity, or output fingerprint. An invalid candidate is rejected without aborting other candidates in the bounded batch.

## Explicit non-goals

The filter does not rank, score, select, recommend, fill missing roles, detect coverage gaps, retrieve library records, inspect image bytes, invoke models, construct prompts, generate assets, access Notion or Drive, publish, or execute production work. It only produces deterministic eligibility groupings from supplied governed evidence.

All authority fields remain `false`.

## Rollback

Rollback is removal or reversion of the additive candidate-filter module, focused fixture and tests, and this document. Module A and all upstream contracts remain independently valid.
