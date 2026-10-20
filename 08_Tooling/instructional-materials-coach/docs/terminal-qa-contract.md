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
- `src/instructional_materials_coach/worksheet_pagination.py` — the pure
  heading keep-with-next resolver and planner (#3416), shared by the build
  and QA observation.
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
7. Worksheet heading pagination (#3416): every `HEADING_1`–`HEADING_6`
   paragraph in the persisted worksheet (body and table cells) has an
   effective `keepWithNext` — the paragraph's own value, else its named
   style's, else `NORMAL_TEXT`'s, else false. A heading without it fails
   with `qa-heading-keep-with-next-missing` (`pagination-unverified`); the
   finding records the exact count and up to 10 headings. This is the
   #3176 rule migrated into the canonical build under #3259 D1/D1b; the
   build applies it before placement, and QA proves it on readback.

**Sufficient:** the conjunction of all necessary checks → `verified` →
terminal admission.

**Advisory:** manual-review findings (e.g. unresolved roles routed from
`worksheet_revision_qa`), omitted-token counts, non-required extras.
Advisory findings never admit terminal success by themselves.

## State taxonomy

`verified` · `token-unresolved` · `content-missing` · `content-mismatch` ·
`pagination-unverified` · `visual-missing` · `visual-mismatch` ·
`placement-unverified` ·
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

Sequential genuine insertions each advance the artifact revision, so
earlier legitimate receipts disagree with the final revision by design.
The receipts are append-only and are never re-stamped with the final
revision. Instead, each completed placement run persists an atomic
**reconciled batch proof** (`visual-placement-batch-proof-v1`) bound to
the ordered complete receipt set, exact asset/content/element identities,
artifact/build identity, the observed final revision, verified
per-insertion mutation continuity (before/after snapshots proving each
insertion changed exactly the marker plus one element), and a
tamper-evident proof fingerprint that QA recomputes. Terminal QA consumes
the proof for the members it revalidates; a missing proof is strict
fail-closed when required (multi-receipt batch →
`qa-batch-proof-missing`), while a conflicting, tampered, or
revision-mismatched proof fails closed (`qa-batch-proof-conflict` /
`qa-batch-proof-invalid` / `qa-artifact-stale`) for manual review --
never verification.

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
- Duplication policing is opt-in per expectation: `qa-content-duplicated`
  fires only when a governed `max_occurrences` is set and exceeded. With
  no `max_occurrences`, repeated content is NOT a failure (#3258 P1
  determination 2026-10-19: the governed plan opts specific expectations
  into duplication policing; terminal QA must not invent a blanket
  duplication rule beyond the plan).

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
  `artifact-stale`. Members revalidated by a verified reconciled batch
  proof are bound to the proof's observed final revision instead of their
  original per-insertion revisions (the originals are preserved, never
  rewritten).
- A batch proof whose fingerprint does not recompute, whose member set
  conflicts with the receipt store, or whose final revision differs from
  the observation fails the whole batch closed; two proofs claiming one
  artifact are conflicting evidence; a multi-receipt batch with no proof
  at all fails closed (`qa-batch-proof-missing`).
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
  (`inlineObjectElement.embeddedObjectId` + `inlineObjects` map); heading
  paragraphs with their effective `keepWithNext` (#3416).
- Slides observation: per-slide text; all page-element object ids (image
  elements carry `image`; the inserted element is matched by id, mirroring
  the #3257 post-insertion verification).
- No parity gap: both paths are implemented and tested.

## Retry and continuation

- QA evidence persists per idempotency key (`reports/terminal-qa/`),
  atomically, bound to expectations hash + artifact revisions.
- Retry with unchanged artifact: a prior `verified` report is recovered
  while revision, expectations, and the exact stored receipt bytes still
  match (no re-evaluation). The recovery identity is the byte fingerprint
  of the receipt store file, which also holds the reconciled batch
  proofs: an unchanged artifact/expectations pair never reuses cached
  verified QA after a receipt was added, removed, or altered, or after a
  proof changed.
- Retry after artifact mutation: revision mismatch → prior proof is NOT
  reused → fresh verification required; terminal success refused until it
  passes.
- Retry after partial QA: failed dimensions are re-evaluated; valid
  prior evidence is never required to be re-proven from scratch, stale
  evidence is never reused.
- Changed expectations invalidate stored proof.
- Evidence is versioned (`terminal-qa-evidence-v2` since #3416): evidence
  recorded under an earlier version predates the heading-pagination check
  and is never recovered.
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

## Cached-success receipt integrity (Phase 1 repair)

Terminal QA evidence contract `terminal-qa-evidence-v3` includes a SHA-256
fingerprint of the exact on-disk placement-receipt snapshot read for the QA
evaluation. Cached `verified` is reusable only when the build key, artifact
identity, artifact revision, governed expectations, and current placement
evidence fingerprint all match. Receipt deletion, substitution, byte changes,
or malformed/unreadable receipt data prevent recovery. Current records are
then independently evaluated, with missing/altered evidence failing closed.
Receipts are not rewritten by terminal QA. Legacy v2 evidence is reverified
instead of being trusted under the stronger v3 cache contract.

Receipt snapshots are read once per run and shared between fingerprinting
and QA evaluation to avoid comparing a different receipt from the one QA
actually consumed. This is cache integrity, not a substitute for the existing
final Docs/Slides content and placement checks.


## Interrupted placement journal and cached terminal QA

An unresolved #3257 insertion-attempt fence prevents terminal QA success
regardless of whether its binding still appears in the current plan. This
check runs before fresh evaluation and before v3 receipt-cache recovery,
including optional-only and zero-current-visual expectation cases. The
verified-receipt hash is not a substitute for attempt-journal inspection.
No attempt fence is automatically cleared by terminal QA: only #3257's
verified placement reconciliation path may clear it.


## Slides image-type and container proof (v4 follow-up)

Terminal verified evidence `terminal-qa-evidence-v4` supersedes prior v3
positive cache entries. A receipt's inserted Slides element must be an
actual `pageElement.image` on the exact slide named by `container_id`. A
matching shape, line, table, or image on another slide is insufficient.
Producer-side insertion/recovery readback requires the same image-type
and exact-slide proof. The existing revision chain, journal, receipt digest,
and identity checks remain mandatory. This is repository-side offline
validation; live Docs/Slides canary acceptance remains separate.
