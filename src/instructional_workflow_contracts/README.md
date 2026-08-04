# Instructional Workflow Contracts

MaterialRequirement remains the sole material-input contract.

## Version compatibility

- curriculum-material-requirement-v1 keeps its existing exact shape and contains no governed visual-direction evidence.
- curriculum-material-requirement-v2 requires the bounded visual_direction group.
- Validation dispatches only by the exact identity.contract_version value.
- No automatic v1-to-v2 conversion occurs.

## Visual direction

Supported decisions are unspecified, no-visuals, and visuals-required. maximum_visual_count must be an exact built-in integer from 0 through 8. Booleans are rejected. visuals-required needs at least one required role, while no-visuals requires zero roles and a zero maximum.

Visual roles use controlled role type, requirement state, instructional purpose, intended placement, and orientation fields. Unknown fields and duplicate semantic roles fail closed. Role ordering and fingerprints are deterministic.

Free-form prose, artifact type, filenames, notes, and prompts are never interpreted as governed visual evidence.

## Visual Needs Planner

`plan_visual_needs` consumes only a structurally valid `MaterialRequirement` and returns one `curriculum-visual-needs-plan-v1` record with exactly one outcome:

- `no-visual-needed` for validated v2 `no-visuals` evidence;
- `visuals-required` for validated v2 `visuals-required` evidence;
- `manual-review-required` for valid v1, validated v2 `unspecified`, or the manual-review material-type sentinel.

The planner preserves required and optional roles separately, assigns deterministic role and plan IDs, binds the exact source requirement ID, revision, contract version, and fingerprint, references the existing material-level accessibility requirements, and uses the governed maximum visual count as the bounded visual/cognitive-load ceiling.

The planner never derives roles from free-form instructional prose or artifact type. It performs no Visual Asset Library retrieval, filtering, ranking, compatibility scoring, missing-role detection, prompt construction, image generation, Notion or Drive access, model call, OCR, embedding, computer-vision, GPU, filesystem write, or network operation.

## Visual Asset Compatibility

`validate_visual_asset_compatibility_evidence` validates one exact Visual Asset Library record, one exact valid `ArtifactManifest`, and one bounded compatibility-evidence group. It distinguishes eligible evidence, hard rejection, manual review, and structurally invalid input without interpreting free-form library metadata as authority.

See `VISUAL_ASSET_COMPATIBILITY.md` for the exact envelope, classifications, fail-closed identity binding, and prohibited operations.

## Visual Asset Candidate Filter

`filter_approved_visual_candidates(visual_needs_plan, candidates, *, source_revision)` consumes only a validated `visuals-required` plan and at most 32 supplied compatibility envelopes. It deterministically groups candidates as eligible, rejected, or manual review by checking governed plan role, material type, and orientation overlap.

The filter performs no ranking, scoring, selection, retrieval, gap detection, prompt construction, image inspection, generation, external access, or production action. `source_revision` is required and identity-bound so a changed source snapshot produces a changed candidate-set ID and fingerprint.

See `VISUAL_ASSET_CANDIDATES.md` for the filter contract and boundaries.

## Authority and downstream behavior

All retrieval, generation, production, publication, approval, readiness, and external-write authority remains false.

Issue #849 may consume only a validated `visuals-required` plan. A `no-visual-needed` or `manual-review-required` plan must not trigger Visual Asset Library retrieval. The plan and filtered candidate set remain advisory and do not authorize selection, use, generation, or publication of an image.

## Rollback

Rollback for the visual eligibility lane is removal or reversion of the additive planner-consumer modules, focused fixtures and tests, and documentation sections. `MaterialRequirement`, `VisualNeedsPlan`, `ArtifactManifest`, and Visual Asset Sync remain independently valid and require no external cleanup or migration.
