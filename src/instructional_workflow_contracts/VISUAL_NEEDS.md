# Visual Needs Planner

Issue #847 adds one pure deterministic planning boundary after validated `MaterialRequirement` evidence and before any Visual Asset Library read.

## Public boundary

Use:

```python
from instructional_workflow_contracts.visual_needs import plan_visual_needs
```

The function accepts a raw `MaterialRequirement`, a valid `ValidationResult`, or a validated `ValidatedRecord`. Every accepted record is reconstructed through `validate_material_requirement`; caller-supplied validated evidence must match the reconstructed identity, revision, contract version, and fingerprint exactly.

The planner returns one `ValidationResult` whose record uses `curriculum-visual-needs-plan-v1`.

## Exact outcomes

Only these outcomes exist:

- `no-visual-needed`
- `visuals-required`
- `manual-review-required`

Routing is fixed:

- valid `curriculum-material-requirement-v1` -> `manual-review-required`;
- valid v2 `unspecified` -> `manual-review-required`;
- valid v2 `no-visuals` -> `no-visual-needed`;
- valid v2 `visuals-required` -> `visuals-required`;
- the validated `unsupported-manual-review` material sentinel -> `manual-review-required`;
- malformed, unsupported, or incompatible upstream evidence -> invalid.

Free-form purpose text, subject metadata, filenames, notes, comments, prompts, and artifact type alone never create visual roles.

## Output evidence

Every plan preserves:

- stable plan ID;
- source requirement ID, revision, exact contract version, and validated fingerprint;
- material type and exact outcome;
- source visual decision when v2 supplies one, including sentinel plans;
- ordered required and optional roles with stable role IDs;
- instructional purpose, placement, orientation, and requirement state for each role;
- a stable reference from each role to material-level accessibility requirements;
- accessibility requirements, maximum visual count, and matching cognitive-load ceiling;
- manual-review state, canonical reason codes, deterministic fingerprint, and an all-false authority block.

The planner supports all validated material types except the explicit `unsupported-manual-review` sentinel. The source contract bounds visual roles and the maximum visual count to eight. Optional roles remain optional, and sentinel plans never authorize roles.

## Determinism and bounds

The planner reuses shared normalization, fingerprinting, immutable payload, validation-result, reason-code, and authority mechanics. The result must fit the shared 16 KiB validated-record limit.

Stable role IDs bind the source requirement fingerprint and complete governed role evidence. Stable plan IDs bind source identity and fingerprint, outcome, decision, roles, accessibility evidence, reason codes, and the visual-count ceiling.

## Authority and side effects

Every authority value remains false. The planner performs:

- zero network, Notion, or Google Drive calls;
- zero model, image-generation, image-analysis, OCR, embedding, vector-search, computer-vision, or GPU work;
- zero filesystem writes, background work, production, publication, approval, readiness, or classroom-material mutation.

A `visuals-required` result defines needs only. It does not prove an approved asset exists or authorize retrieval. Issue #849 may consume only a valid `visuals-required` plan.

## Offline validation

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_visual_needs_plan.py -q
PYTHONPATH=src python3 -m pytest tests/test_material_requirement_contract.py tests/test_instructional_workflow_contract_integration.py -q
bash 07_Agent_Tests/validate-repo-structure.sh
./scripts/validate-all.sh
```

Known environment failures must be reproduced on clean `main` rather than weakening validation.

## Rollback

Rollback removes the planner module, focused documentation, test module, and synthetic fixture. No Notion, Drive, credential, production, asset, or classroom-artifact cleanup is required because the planner performs no external read or write.
