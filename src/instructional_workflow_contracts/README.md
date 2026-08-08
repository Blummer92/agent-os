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

`validate_visual_asset_compatibility_evidence` supports two exact versions:

- `curriculum-visual-asset-compatibility-v1`, which preserves the existing compatibility shape and behavior;
- `curriculum-visual-asset-compatibility-v2`, which requires a complete governed `cohesion_profile` and preserves expanded matched-asset context and lifecycle metadata.

Dispatch uses only the exact `compatibility_evidence.contract_version`. V1 rejects v2-only fields, v2 requires its complete profile, unsupported versions fail closed, and no automatic version conversion occurs. The validator binds one Visual Asset Library record to one exact validated manifest and asset identity; classifies evidence as eligible, hard rejection, or manual review; and returns invalid status for malformed evidence.

The v2 profile preserves controlled visual style family, medium, representation class, palette family, line treatment, rendering style, perspective, background treatment, 1-through-5 complexity and cognitive-load ratings, and attributable human-reviewed audience compatibility. Required `unspecified`, stale, contradictory, pending, not-assessed, or unattributed evidence routes to manual review rather than receiving a fabricated default.

See `VISUAL_ASSET_COMPATIBILITY.md` for exact vocabularies, evidence fields, ownership, classification rules, identity binding, projected manifest and asset metadata, and prohibited operations.

## Visual Asset Candidate Filter

`filter_approved_visual_candidates(visual_needs_plan, candidates, *, source_revision, contract_version=CONTRACT_ID)` supports:

- `curriculum-visual-asset-candidates-v1`, which remains the default and preserves the existing compact entry shape;
- `curriculum-visual-asset-candidates-v2`, which must be selected explicitly and accepts only v2 compatibility evidence.

There is no automatic conversion between candidate or compatibility versions. A compatibility record from the wrong version is rejected as invalid. Both versions consume only an exactly validated `visuals-required` plan and at most 32 supplied compatibility envelopes, preserve exact plan and source-revision binding, and deterministically group candidates as eligible, rejected, or manual review.

V2 preserves a compact projection of the exact validated compatibility record: compatibility identity and fingerprint, manifest verification identity, asset identity, Visual Asset Library and Drive identity, purpose and approved-use evidence, orientation and aspect state, accessibility, freshness, duplicate and canonical disposition, context and lifecycle metadata, the complete cohesion profile, and all-false authority. The filter does not reconstruct those fields later from free-form working data.

The filter performs no cohesion ranking, scoring, selection, role assignment, retrieval, gap detection, prompt construction, image inspection, generation, external access, or production action. `source_revision`, the exact plan identity, selected contract version, ordered candidate groups, and projected evidence are bound into deterministic candidate-set identity and SHA-256 fingerprinting.

See `VISUAL_ASSET_CANDIDATES.md` for exact v1 and v2 entry shapes, group behavior, reason-code mappings, bounds, and prohibited operations.

## Current Curriculum State

`resolve_current_curriculum_state` consumes only bounded caller-supplied provider-neutral evidence with `contract_version` exactly `curriculum-current-state-evidence-v1`; other versions fail closed with `handoff-version-unsupported`. It returns one deterministic `curriculum-current-state-v1` record and does not read Notion, Drive, GitHub, files, environment variables, credentials, or models.

Canonical owner evidence remains authoritative even when newer narrative, display-derived, or agent-suggested evidence disagrees. Newer narrative may surface a contradiction but cannot overwrite owner state; stale material owner evidence, conflicting owner values, or unresolved relations fail closed into reconciliation, decision, or blocked dispositions.

Relative requests such as `tomorrow` require explicit current-day evidence and supplied ordered-day context. Packet order, creation time, filenames, inferred sequence, formulas, rollups, and routing suggestions are not treated as authority.

Asset existence, approval for the requested use, approved reusable student-facing eligibility, and production authorization remain separate facts. The resolver does not implement [#971](https://github.com/Blummer92/agent-os/issues/971) association behavior or [#963](https://github.com/Blummer92/agent-os/issues/963) persistence/write proposals.

All resolver execution, Notion-write, Drive-write, external-write, publication, and production authority remains false.

## Authority and downstream behavior

All retrieval, generation, production, publication, approval, readiness, and external-write authority remains false.

Issue #849 may consume only a validated `visuals-required` plan. A `no-visual-needed` or `manual-review-required` plan must not trigger Visual Asset Library retrieval. The plan and filtered candidate set remain advisory and do not authorize selection, use, generation, or publication of an image.

## Rollback

Rollback for the visual eligibility lane is removal or reversion of the additive planner-consumer modules, focused fixtures and tests, and documentation sections. `MaterialRequirement`, `VisualNeedsPlan`, `ArtifactManifest`, and Visual Asset Sync remain independently valid and require no external cleanup or migration.