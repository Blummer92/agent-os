# Terminal artifact-content QA contract (#3258)

## Invariant

Agent OS calls an instructional artifact complete only when it can prove
that the persisted final artifact contains the governed required content
and governed required visuals, attributable to the current build and
artifact state.

A build must NOT be declared complete solely because generation succeeded,
text replacement succeeded, visual placement succeeded, a placement receipt
exists, a Google Doc/Slides artifact exists, an export succeeded, or
repository tests are green.

## Where it lives

- `src/instructional_materials_coach/artifact_content_qa.py` — the QA
  contract: expectations, persisted-artifact observation, evaluation,
  machine-readable reports, durable evidence store.
- `src/instructional_materials_coach/live_build.py` — terminal admission:
  `LiveBuildReceipt.succeeded` (the single completion owner) requires both
  artifacts terminal-QA `verified`. `ArtifactReceipt.is_persisted`
  distinguishes metadata-verified from final.
- `src/instructional_materials_coach/cli.py` — builds expectations from the
  governed planned inputs, prints "final" only on QA pass, and names QA
  states in failure reports. New flag: `--qa-evidence-dir`
  (default `reports/terminal-qa`).

## Execution order

governed plan → content generation/composition → visual selection →
asset/slot resolution → exact content verification → placement request →
persisted artifact placement → post-placement verification → durable
verified PlacementReceipt → **artifact-content QA** → **terminal admission**

QA runs inside `build_live_materials`, after final-copy verification and
the #3257 visual backstop, on every terminal attempt — including the #3252
resume fast path. QA is read-only: no external mutation. A mutated artifact
can never ride a stale success to "final".

## What terminal proof requires

**Necessary** (each required for terminal success):

1. Artifact identity: the inspected artifact is the built artifact
   (artifact id binding on every observation and receipt).
2. Artifact state: evidence is bound to the current artifact revision;
   stale or conflicting evidence fails closed (`artifact-stale`,
   `artifact-conflict`).
3. Required text present and correct: every governed `replaceAllText`
   token is gone from the persisted artifact and its replacement text is
   present (`token-unresolved`, `content-missing`).
4. Required visuals verified: every required role/slot has a verified
   placement receipt bound to this artifact, the receipt's asset and exact
   content identity match the governed selection, the receipt's
   post-placement revision matches the current artifact revision, the
   visual marker is gone, and the inserted element is observable in the
   persisted artifact (`visual-missing`, `visual-mismatch`,
   `placement-unverified`, `artifact-stale`).
5. Build attribution: expectations and evidence are bound to the same
   build idempotency key.
6. Readback succeeded: the persisted artifact was actually read
   (`artifact-inaccessible`, `verification-runtime-unavailable` refuse
   terminal success — never silent).

**Sufficient:** the conjunction of all necessary checks → `verified` →
terminal admission.

**Advisory:** manual-review findings (e.g. unresolved roles routed from
`worksheet_revision_qa`), omitted-token counts, non-required extras.
Advisory findings never admit terminal success by themselves.

## State taxonomy

`verified` · `token-unresolved` · `content-missing` · `content-mismatch` ·
`visual-missing` · `visual-mismatch` · `placement-unverified` ·
`artifact-stale` · `artifact-inaccessible` · `artifact-conflict` ·
`evidence-incomplete` · `verification-runtime-unavailable` (+ `not-run`
before QA executes).

Visual proof failures outrank generic token/content failures in
aggregation because they carry role/slot/receipt attribution; the
token-level finding is always still recorded.

## Why receipts alone are insufficient

#3257 receipts prove insertion + identity attribution at placement time.
They do not prove the final artifact still contains the content: the
artifact may have mutated after placement (receipt revision ≠ current
revision → `artifact-stale`), the receipt may reference another artifact
(`artifact-conflict`), or the persisted visual may be unobservable
(`visual-mismatch`). QA re-binds every receipt to the inspected artifact
state at terminal time.

## Text proof

- Expectations derive from the governed planned `replaceAllText`
  requests: `containsText` token (must be absent) + `replaceText` (must be
  present). Nothing is inferred beyond the plan.
- Global unresolved-token scan (`{{...}}`) over the observed artifact
  text; any hit fails QA with a token-level finding.
- Normalization is whitespace-folding ONLY: no case folding, no
  punctuation stripping, no fuzzy matching — it cannot permit materially
  incorrect content (`matchCase` semantics preserved).
- Optional per-expectation `location_hint` (e.g. slide index) and
  `max_occurrences` (invalid duplication → `content-mismatch`). The
  current build path does not populate location hints: location defaults
  to artifact-wide (documented intentional limitation, no false failures).

## Visual proof

Consumes Wave 3 placement evidence; does not reimplement selection or
placement:

required role → governed selected Asset ID → exact content identity →
verified PlacementReceipt → receiving artifact identity → persisted
artifact observation → expected target → QA result.

- A required visual with no verified receipt in ANY artifact →
  `placement-unverified`, with the role named for manual review.
- A required visual verified-placed in another artifact (marker routing)
  is not demanded in this artifact.
- Receipt-to-artifact binding: artifact id, asset id, exact content
  identity, and post-insertion revision must all match the inspected
  state; mismatch → `artifact-conflict` / `visual-mismatch` /
  `artifact-stale`.
- Persisted observation: the `{{visual:<role>}}` marker must be gone and
  the receipt's `inserted_element_id` must be present among the observed
  elements (Docs inline objects; Slides page elements).
- The existing `worksheet_revision_qa.validate_revision_render_visuals` /
  `visual_completeness` contracts are wired into this dimension (required
  roles verified against the persisted render, keyed to stable role
  identities; unresolved roles route to manual review, never a false pass).

Correspondence limit (honest): byte-level correspondence between persisted
image bytes and the Drive asset is not observable through the Docs/Slides
read APIs. Correspondence is established through the receipt chain
(pre-placement #3256 content-identity verification + #3257 post-insertion
marker/target verification) plus QA's artifact/revision binding. See
"Live-acceptance boundary".

## Docs vs Slides

Both artifact types share the contract. Capability differences:

- Docs observation: body paragraphs + tables text; inline objects
  (`inlineObjectElement.embeddedObjectId` + `inlineObjects` map).
- Slides observation: per-slide text; all page-element object ids (image
  elements carry `image`; the inserted element is matched by id, mirroring
  the #3257 post-insertion verification).
- No parity gap: both paths are implemented and tested.

## Retry and continuation

- QA evidence persists per idempotency key (`reports/terminal-qa/`),
  atomically, bound to expectations hash + artifact revisions.
- Retry with unchanged artifact: a prior `verified` report is recovered
  while revision and expectations still match (no re-evaluation).
- Retry after artifact mutation: revision mismatch → prior proof is NOT
  reused → fresh verification required; terminal success refused until it
  passes.
- Retry after partial QA: failed dimensions are re-evaluated; valid
  prior evidence is never required to be re-proven from scratch, stale
  evidence is never reused.
- Changed expectations invalidate stored proof.
- Retries perform no external mutations (QA is read-only).

## What blocks terminal completion

Any QA state other than `verified` on either artifact; missing
expectations (`evidence-incomplete`); unreadable artifacts
(`artifact-inaccessible`); no readback capability
(`verification-runtime-unavailable`); stale/conflicting evidence. The CLI
prints "final" only when `LiveBuildReceipt.succeeded` — i.e. both
artifacts QA-`verified`.

## Live-acceptance boundary

Repository-level proof (this contract) is established through
injected-client readback fixtures: observation, evaluation, binding,
staleness, retry, and admission are all proven without external calls.

Pending separately governed live acceptance (same as #3257): real
Docs/Slides execution through the deployed Apps Script placement runtime.
Until that activation:

- no claim is made about real external artifact proof;
- live-execution placement receipts do not exist; the receipt store
  carries repository-acceptance receipts;
- repository-level QA is NOT weakened because live acceptance is pending.

## Ownership

#3258 owns terminal finality over all rendered content. #3257 owns
positive placement evidence only. Neither reimplements the other.
