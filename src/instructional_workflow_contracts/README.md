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

## Authority and downstream behavior

All retrieval, generation, production, publication, approval, readiness, and external-write authority remains false.

Issue #847 must route valid v1 records and valid v2 unspecified records to manual-review-required. It may consume governed visual evidence only from validated v2 records.
