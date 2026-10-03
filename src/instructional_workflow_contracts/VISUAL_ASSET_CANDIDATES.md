# Visual Asset Candidate Filtering

`filter_approved_visual_candidates(visual_needs_plan, candidates, *, source_revision, contract_version=CONTRACT_ID)` is the pure deterministic candidate-filter boundary.

Supported IDs are `curriculum-visual-asset-candidates-v1` and `curriculum-visual-asset-candidates-v2`. `CONTRACT_ID` and the function default remain v1. V2 requires explicit `contract_version=V2_CONTRACT_ID` (or its exact string); unsupported versions fail closed, and no v1/v2 conversion occurs.

## Version and input rules

Candidate v1 accepts only `curriculum-visual-asset-compatibility-v1`; candidate v2 accepts only `curriculum-visual-asset-compatibility-v2`. A valid record from the wrong version is `rejected` as `invalid` with `visual-candidate-contract-incompatible`, without conversion or expanded projection. V1 entry shape, identity inputs, ordering, and default behavior remain unchanged.

Inputs are bounded as follows:

- `visual_needs_plan`: validated `curriculum-visual-needs-plan-v1` `ValidationResult` or `ValidatedRecord` with exact `visuals-required` outcome; contract version, plan ID, revision, and fingerprint must reconstruct exactly.
- `candidates`: built-in list of at most 64 compatibility envelopes (`MAX_CANDIDATES`), each revalidated independently. Above 64 the query is `INVALID` with the explicit `capacity-exceeded` reason code: an input-contract violation, never absence or review.
- `source_revision`: nonempty caller-supplied source-snapshot identity, at most `MAX_SOURCE_REVISION_LENGTH` (`256`) characters.
- `contract_version`: exact candidate projection version; defaults to v1.

Plain plan mappings, `no-visual-needed`, and `manual-review-required` plans fail closed.

## Deterministic classification

Each candidate enters exactly one ordered group:

- `eligible`: compatibility is eligible, at least one governed plan role overlaps compatible and approved roles, the plan material type is approved, and governed orientation is satisfied.
- `rejected`: invalid input, hard rejection, incompatible contract version, or role/material/orientation mismatch.
- `manual_review`: compatibility is `manual-review-required`.

Plan mismatches use `visual-candidate-role-mismatch`, `visual-candidate-material-mismatch`, and `visual-candidate-orientation-mismatch`. One invalid candidate cannot corrupt valid bounded siblings. The filter never compares cohesion profiles, ranks, scores, recommends, selects a cohesive set, assigns roles, or detects missing-role coverage.

## Candidate-set binding

The result preserves plan contract version, plan ID, plan revision, and plan fingerprint. `candidate_set_id` is deterministic and SHA-256-derived from the selected candidate contract, exact plan identity, exact `source_revision`, and the compact classification references for the fully ordered `eligible`, `rejected`, and `manual_review` groups. Each reference fingerprint binds the exact validated compatibility record bytes, so the set identity is transport-independent. The validated result fingerprint covers the complete normalized result.

Input order does not affect semantic output. Groups sort by compatibility ID, compatibility fingerprint, reason codes, and canonical `sha256_hex(item)` as the total-order tie-breaker. Changing source revision, version, plan identity, evidence, classification, reasons, or projected fields changes the candidate-set identity or fingerprint.

## V1 projection

V1 entries remain exactly: `compatibility_id`, `fingerprint`, `classification`, `reason_codes`, `asset_reference`, and `library_reference`. Invalid entries use `null` where identity/reference evidence is unavailable. V1 never receives the expanded v2 projection.

## V2 projection

Every v2 entry backed by the expected validated compatibility version preserves:

- compatibility binding: `compatibility_contract_version`, `compatibility_id`, `compatibility_record_revision`, `fingerprint`, `classification`, and `reason_codes`;
- `manifest_reference`: manifest ID, revision, fingerprint, verification timestamp, and external file ID;
- `asset_reference`: asset ID, stable reference, and content fingerprint;
- `library_reference`: Visual Asset Library page ID and Drive file ID;
- `purpose`, `approved_use`, `orientation`, `accessibility`, and `freshness` evidence;
- `matched_asset`: duplicate relationship, disposition, canonical reference, duplicate group, required/preserved context, context completeness, direct-use status, repair-source status, and replacement-required state;
- complete governed `cohesion_profile` and exact all-false `authority`.

Invalid or wrong-version v2 envelopes preserve only available compatibility-binding fields, `classification: invalid`, and reason codes. The filter never reconstructs manifest, asset, approved-use, accessibility, freshness, lifecycle, context, or cohesion evidence from working inputs. `matched_asset` carries the asset-level duplicate/disposition/direct-use/repair/replacement lifecycle evidence; manifest-level `operation`, `lineage`, and `statuses` are not projected by this contract.

## Result, bounds, and authority

The immutable result contains selected contract version, deterministic candidate-set ID, exact source revision, exact plan identity, `maximum_candidate_count: 64`, actual count, the three ordered groups, a `capacity_exceeded` group (populated only when the bounded transport cannot carry a classified entry), the `projection_transport` marker (`inline` or `by-reference`), and all-false candidate-set authority. Shared serialized-size limits apply.

### Projection transport (#3255)

The result record is bounded by the shared 16 KiB result limit. While the full inline result fits, entries carry their complete validated projections exactly as before. When the inline form would exceed the bound, the filter hands candidates off by reference: each entry becomes the compact `{compatibility_id, fingerprint, classification, reason_codes}` reference, and the cohesive planner resolves references through a caller-supplied projection store -- a mapping keyed by `(compatibility_id, fingerprint)` whose values are the validated compatibility records -- fingerprint-verifying each before selection. The resolved candidate dicts are byte-identical to the inline entries, so selection is transport-independent. A missing store, or a missing or mismatched projection, fails closed.

If even the by-reference form cannot fit the bound, references degrade per item to the explicit `capacity-exceeded` outcome (never the whole query, never absence, never review). The input count bound above 64 remains whole-query `INVALID` with the `capacity-exceeded` reason code.

Any manual-review candidate produces `ValidationStatus.MANUAL_REVIEW_REQUIRED`; otherwise a structurally valid set is `ValidationStatus.VALID`.

Execution, external write, production, publication, and performed-side-effect authority remain false. Contract-specific authority fields stay false; governing no-side-effect requirements remain under `00_Governance/write-authorization-policy.md` and `01_Shared_Standards/github/safe-implementation-lane.md`.

## Rollback

Rollback removes only additive v2 candidate projection from `src/instructional_workflow_contracts/visual_asset_candidates.py`, `src/instructional_workflow_contracts/VISUAL_ASSET_CANDIDATES.md`, `tests/fixtures/instructional_workflow_contracts/visual_asset_candidate_v2_cases.json`, and `tests/test_visual_asset_candidates.py`. Candidate v1, compatibility v1, and upstream contracts remain independently valid without migration or external cleanup.
