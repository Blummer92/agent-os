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
- material type;
- exact outcome;
- source visual decision when v2 supplies one;
- ordered required and optional roles;
- stable role IDs;
- instructional purpose, placement, orientation, and requirement state for each role;
- a stable reference from each role to the material-level accessibility requirements;
- accessibility requirements;
- maximum visual count;
- cognitive-load ceiling equal to the governed maximum visual count;
- manual-review state and canonical reason codes;
- deterministic fingerprint;
- an all-false authority block.

The planner supports all validated material types except the explicit `unsupported-manual-review` sentinel. The source contract bounds visual roles and the maximum visual count to eight. Optional roles remain optional.

## Determinism and bounds

The planner reuses shared normalization, fingerprinting, immutable payload, validation-result, reason-code, and authority mechanics. The result must fit the shared 16 KiB validated-record limit.

Stable role IDs bind the source requirement fingerprint and the complete governed role evidence. Stable plan IDs bind the source requirement identity and fingerprint, outcome, decision, roles, accessibility evidence, reason codes, and visual-count ceiling.

## Authority and side effects

Every authority value remains false. The planner performs:

- zero network calls;
- zero Notion or Google Drive calls;
- zero model calls;
- zero image generation or image analysis;
- zero OCR, embedding, vector-search, computer-vision, or GPU work;
- zero filesystem writes;
- zero background work;
- zero production, publication, approval, readiness, or classroom-material mutation.

A `visuals-required` result defines needs only. It does not prove that an approved asset exists and does not authorize retrieval. Issue #849 may consume only a valid `visuals-required` plan.

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

Rollback removes:

- `src/instructional_workflow_contracts/visual_needs.py`;
- `src/instructional_workflow_contracts/VISUAL_NEEDS.md`;
- the focused test module;
- the synthetic visual-needs fixture.

No Notion, Drive, credential, production, asset, or classroom-artifact cleanup is required because this planner performs no external read or write.
