# Cohesive Visual Plan Contract

## Purpose

`curriculum-cohesive-visual-plan-v1` is the pure-local post-filter planning boundary for Issue #851. It consumes one validated `VisualNeedsPlan` with outcome `visuals-required` and one matching v2 approved-candidate filter result, then produces one deterministic advisory plan for a cohesive visual set.

The contract does not retrieve, decode, generate, upload, approve, publish, or insert images. It performs no Notion, Drive, Docs, Slides, Sheets, model, OCR, embedding, vector, computer-vision, GPU, network, production, or classroom-artifact operation.

## Inputs

The planner accepts only validated evidence:

- `curriculum-visual-needs-plan-v1` with outcome `visuals-required`.
- `curriculum-visual-asset-candidates-v2` bound to the exact plan ID, revision, contract version, and fingerprint.

The v2 candidate result must already contain eligible candidates from the upstream candidate filter. The cohesive planner never restores rejected or manual-review candidates into eligibility.

## Output

The result record includes:

- stable plan identity and SHA-256 fingerprint;
- source visual-needs plan identity;
- source candidate-filter identity;
- outcome: `complete-set`, `partial-set`, or `manual-review-required`;
- required role assignments;
- optional role assignments;
- selected candidate identities;
- rejected assignment evidence;
- rejected set-combination evidence;
- unfilled required and optional roles;
- one deterministic image-gap brief per unfilled required role;
- cognitive-load total and ceiling;
- manual-review reasons;
- all-false authority.

## Selection behavior

The planner evaluates required roles before optional roles. A candidate may be assigned only when it matches the role type, approved use, material type, orientation policy, complete governed cohesion evidence, and approved audience evidence.

Hard set checks run before assignment:

- duplicate or equivalent selected assets are rejected;
- cohesion conflicts are rejected across style family, medium, representation class, palette family, line treatment, rendering style, perspective, and background treatment;
- cognitive load must remain within the governed ceiling.

Scoring is bounded and integer-based. It prefers exact role and approved-use matches, canonical assets, orientation matches, and lower cognitive load. Stable tie-breaking is deterministic, but a truly equal top assignment routes to manual review instead of pretending certainty.

## Gap briefs

Every unfilled required role produces exactly one vendor-neutral brief. The brief preserves role ID, role type, instructional purpose, material type, placement, orientation, approved reference asset IDs when available, draft alt text, accessibility considerations, and all-false authority.

When governed metadata does not support a brief field, the planner records `unspecified` rather than inventing composition, palette, perspective, line treatment, shading, dimensions, or style evidence.

## Authority boundary

A `complete-set` means only that the pure planner found a deterministic advisory assignment from already eligible candidates. It does not authorize classroom use, publication, approval, readiness mutation, external writes, image generation, upload, or insertion into student-facing materials.

`partial-set` means at least one required role remains unfilled and requires human follow-up through the emitted image-gap briefs.

`manual-review-required` means the planner found evidence it cannot safely resolve automatically, such as manual-review candidate evidence or a tied top assignment.

## Rollback

Rollback is removal of:

- `cohesive_visual_plan.py`;
- focused tests for the cohesive visual plan;
- this documentation file.

No Notion repair, Drive repair, credential revocation, image cleanup, classroom-artifact cleanup, production rollback, or external-system migration is required.
