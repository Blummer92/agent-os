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

## Role identity and slots (#3251)

Each role carries a stable `role_id` derived ONLY from the governed
semantic role key (`role_type`, `instructional_purpose`,
`intended_placement`, `orientation`) under the
`visual-role-semantic-key-v1` contract namespace. Requirement
fingerprints, revisions, `requirement_state`, and unrelated record fields
are deliberately excluded: editing a role's semantics changes only that
role's identity, and irrelevant edits or revision bumps never do. Plan
IDs still bind the source requirement fingerprint -- plan identity
changes when the requirement changes; role identity does not.

A role may declare an optional explicit `slots` list: one semantic role
binds one placement per declared slot ID. Slots are placement bindings,
never role identity -- they do not enter the semantic key or the
`role_id`. A role with no declared slots fills the single implicit slot
`"0"`. Every downstream binding keys on `(role_id, slot_id)`: candidate
filtering evaluates each role individually (same-type roles never
collapse), cohesive planning emits one assignment per `(role, slot)`,
and placement markers address `{{visual:<role_id>}}` or
`{{visual:<role_id>:<slot_id>}}`.

A role may also carry an optional author-supplied `concept` reference
(#3254), carried through onto the planned role for gap briefs and image
intents; it never enters role identity either.

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

The planner supports all validated material types except the explicit `unsupported-manual-review` sentinel. The source contract bounds visual roles to eight (`MAX_VISUAL_ROLES`), slots to sixteen per role (`MAX_SLOTS_PER_ROLE`), total role/slot bindings to sixty-four per requirement (`MAX_ROLE_SLOT_BINDINGS`), and the maximum visual count to eight. Optional roles remain optional, and sentinel plans never authorize roles.

## Determinism and bounds

The planner reuses shared normalization, fingerprinting, immutable payload, validation-result, reason-code, and authority mechanics. The result must fit the shared 16 KiB validated-record limit.

Stable role IDs bind the governed semantic role key only (see "Role
identity and slots" above) -- never the source requirement fingerprint.
Stable plan IDs bind source identity and fingerprint, outcome, decision,
roles, accessibility evidence, reason codes, and the visual-count ceiling.

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
