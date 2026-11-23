# Connected Visual Placement Contract (#3257)

One connected path from an authorized visual selection to a verified,
persisted placement in the generated Slides/Docs artifact.

## Production boundary

```
governed visual requirement
  -> eligible reusable asset (#3253/#3254: eligibility evidence, consumed not inferred)
  -> selected logical Asset ID (#3104 identity scoping: visual-asset-{sha256[:24]})
  -> exact content/revision identity (#3256: governed-asset-content-identity-v1)
  -> durable teacher/automatic selection (#3252: teacher-decision records / governed plan)
  -> VisualPlacementBinding (role_id, slot_id, asset_id, drive_file_id,
     content_identity, source_plan_id, required, eligibility_evidence)
  -> marker discovery in the live artifact ({{visual:<role_id>}})
  -> resolve_exact_target (#2087: exactly one pre-discovered match)
  -> build_placement_request (#2087)
  -> verify_request_content_identity vs fresh Drive metadata (#3256)
  -> placement_transport.insert_placement (connected boundary)
  -> post-insertion verification against the persisted artifact
  -> verify_placement_receipt (#2087 -> state "verified")
  -> durable receipt in placement_receipts/ (the #3258 handoff surface)
  -> atomic reconciled batch proof (#3258: ordered complete receipt set
     bound to the observed final revision with verified per-insertion
     mutation continuity)
  -> artifact completion (only when every required slot is verified-placed)
```

## What was reused (not rebuilt)

- `visual_placement.py` (#2087): `PlacementRequest` / `PlacementTarget` /
  `PlacementReceipt`, marker syntax `{{visual:<role_id>}}`, exact-single-match
  resolution, content-identity binding, receipt verification, retry safety.
- `apps-script/VisualPlacementTransport.gs` (#2087): the reference `BlobSource`
  insertion runtime (private Drive file read by exact file ID; no sharing
  change, no public URL, no re-selection).
- `asset_content_identity.py` (#3256): identity precedence
  sha256 > md5 > headRevisionId; explicit verify outcomes.
- `reusable_visual_identity.py` / `visual_reuse.py` (#3104/#3248): Asset ID,
  external identity, conflict fail-closed, reuse-first, proven-absence-only gaps.
- `asset_slot_resolution.py` + `drive_client` classifiers (#3130/#3256): live
  slot resolution with `not-found` / `no-access` / `unresolvable` outcomes.
- `live_build.py`: revision-bound batch writes, idempotent copy recovery,
  per-request resume. Placement rides this lifecycle; it does not duplicate it.
- `teacher_decisions.py` / `build_resume.py` (#3252): durable selection and
  retry continuation. Placement consumes the plan; it never reconstructs
  selection from conversation memory.

## What #3257 added

- `connected_visual_placement.py`: marker discovery (Docs paragraphs, Slides
  shapes), `VisualPlacementBinding` planning from the governed plan,
  `execute_artifact_visual_placements` (per-artifact orchestration with
  recovery-first retry), `require_all_required_visuals_placed`
  (completion backstop).
- `placement_transport.py`: the `PlacementTransport` protocol,
  `PlacementRuntimeUnavailable`, `PlacementTransportError`, and
  `AppsScriptPlacementTransport` (Execution API client for the deployed
  reference script). The adapter enforces revision identity end to end:
  `_request_payload` refuses a request whose target carries no artifact
  revision id; `insert_placement` rejects the pre-repair synthetic
  `docs-child-<index>` element id (never a real persisted Docs inline
  object id) and requires the hardened reference's read-back
  post-placement revision evidence. These raises are plain
  `PlacementTransportError` (never `PlacementNoMutation`): the retry
  logic keeps the attempt fence on all of them, so no retry may reinsert
  blindly.
- `placement_receipts.py`: atomic, per-idempotency-key durable receipt store
  with duplicate-verified-receipt refusal and content-identity-aware recovery.
- `live_build.py`: `LiveBuildInput.visual_placements`, per-artifact placement
  between text requests and final-copy verification, required-placement
  completion backstop.
- `cli.py`: `_require_visual_placement_support` is now the
  `placement-runtime-unavailable` admission gate (replacing the dead-end
  refusal); `--placement-script-id` / `--placement-receipts-dir`.

## Placement identity

```
role_id (+ slot_id)
  -> logical Asset ID (visual-asset-...)
  -> provider identity (google-drive file_id)
  -> exact content/revision identity (governed-asset-content-identity-v1)
  -> target (artifact_type, artifact_id, revision, marker, container/element)
  -> PlacementReceipt (state "verified", inserted_element_id)
```

A receipt proves: the operation succeeded; the intended artifact was
targeted; the intended marker was used; the role/slot was fulfilled; the
logical Asset ID, provider identity, and exact content identity match the
governed selection; the inserted element exists in the persisted artifact;
no unresolved placement error remains.

## Failure taxonomy (all fail closed, none become absence)

| Reason | Meaning |
|---|---|
| `placement-runtime-unavailable` | selection exists, no placement runtime configured/activated |
| `asset-missing` | Drive file not-found -> blocked as missing, not a gap |
| `asset-access-failure` | Drive file no-access -> blocked as access failure, not absence |
| `asset-unverifiable` | Drive lookup failed -> fail closed |
| `content-identity-mismatch` / `-unverifiable` / `-not-recorded` | live bytes differ from approved identity -> never placed silently |
| `marker-not-found` / `marker-ambiguous` | marker coverage problem -> placement failure, not absence |
| `placement-transport-failed` | runtime error -> explicit, never generation permission |
| `placement-receipt-rejected` | transport claim failed verification |
| `post-insertion-verification-failed` | persisted artifact does not show the placement |
| `placement-eligibility-evidence-missing` | upstream evidence breach -> fail closed |
| `placement-binding-ambiguous` / `-incomplete` | binding construction breach -> fail closed |
| `placement-continuity-unverifiable` | artifact unreadable around an insertion -> fail closed |
| `placement-continuity-broken` | insertion changed text/elements beyond the single marker removal + one element -> external/intervening mutation suspected |
| `placement-element-id-reused` | transport reported an element id already present before insertion -> same-ID byte replacement rejected |
| `placement-element-id-missing` | transport reported no inserted element id -> insertion unprovable |
| `placement-batch-unreconciled` | revision/continuity chain broken, unexplained drift, or unobservable member -> no batch proof written |

No failure path emits an image gap brief or authorizes new visual creation.

## Batch reconciliation (#3258)

Sequential genuine insertions each advance the artifact revision, so
earlier legitimate receipts disagree with the final revision by design.
The original per-insertion receipts are append-only and are never
re-stamped with the final revision. Instead:

- `_place_one_binding` observes the artifact immediately before and
  after the transport call (the same observation surface terminal QA
  consumes). The only permitted delta is the single placement marker's
  removal plus exactly the reported inserted element; anything else --
  external/intervening text or element mutations, reused element ids --
  fails the insertion closed (the attempt fence stays held, so a failed
  continuity check can never be retried into a duplicate insertion).
- `execute_artifact_visual_placements` reconciles the completed run: the
  insertion chain must link (first pre-revision = run initial, each post
  = next pre, last post = final; text digests and element sets must link
  too), recovered members must have been reconciled by a prior proof (or
  predate proofs with the artifact unmoved since their insertion), and
  every member's element must be observable in the final snapshot.
- `reconcile_placement_batch` persists one atomic batch proof
  (`visual-placement-batch-proof-v1`) per artifact, superseding the
  previous proof for that artifact. The proof binds the ordered complete
  receipt set (with original per-insertion revisions preserved), exact
  asset/content/element identities, artifact/build identity, the observed
  final revision, the verified per-insertion continuity, and a
  tamper-evident proof fingerprint that terminal QA recomputes when it
  consumes the proof. The proof-side artifact field is
  `batch_artifact_type`, deliberately distinct from the receipt
  envelope's `artifact_type`.

Terminal QA consumes the proof for members it revalidates. A missing
proof is strict fail-closed when required (multi-receipt batch):
`qa-batch-proof-missing` for manual review, never a permissive
per-receipt fallback. Conflicting, tampered, or revision-mismatched
proofs fail closed (`qa-batch-proof-conflict` / `qa-batch-proof-invalid`
/ `qa-artifact-stale`) for manual review -- never verification.

## Retry / continuation (#3252 semantics)

- Retry before placement: safe replay; bindings with no verified receipt are
  attempted normally.
- Retry after successful placement: the durable receipt is recovered by
  (role_id, slot_id, artifact_type, artifact_id, content_identity); the
  image is not inserted again. Recovery precedes marker discovery because a
  successful placement removes the marker.
- Retry after partial placement: already-placed bindings recover; only
  unresolved bindings continue; stale/conflicting/failed bindings keep
  their explicit reasons.
- Every completed run (including recovery-only runs) re-reconciles its
  complete receipt set against the current artifact snapshot and
  supersedes the batch proof; unexplained drift since the last
  reconciliation fails the run closed with no new proof.
- Continuation after a teacher decision: the plan re-honors the durable
  decision; placement consumes the resulting binding unchanged.

## Producer-side recovery readback (local #3257 repair)

A recovered receipt is **not** sufficient by itself: the exact governed
asset/Drive file/source plan must still match, and the persisted Docs/Slides
artifact must still contain the recorded inserted element in the recorded
container with no unresolved marker. Docs verifies both `inlineObjects` and
the document-body inline-object reference. A stale/conflicting receipt is a
`placement-recovery-stale` or `placement-recovery-conflict` failure, never a
successful recovery and never permission to insert another image blindly.

This is offline repository-side hardening, **not live Docs/Slides acceptance**.
Neither the original asset bytes nor a visual's semantic placement can be
reconstructed from an element ID alone. Unreceipted orphan images after an
unknown-outcome transport timeout still require governed reconciliation; the
completion backstop must refuse finality. Live Apps Script deployment and
execution rights remain separately governed. Producer revision-ID changes in
PR #3651 are out of scope for this patch.

## Interrupted insertion and revision-continuity fence (#3257 Phase 2)

Before invoking the transport, the repository durably creates an **exclusive**
per-build, per-artifact, per-role/slot attempt fence alongside the existing
receipt ledger (`.attempts-<build-digest>/<identity-digest>.json`).
Short hashed path components avoid Windows MAX_PATH failures; the build
digest keeps separate idempotency keys from sharing a fence directory. A crash after the
remote image mutation but before receipt persistence leaves this fence. A
retry MUST block with `placement-reconciliation-required` even when a marker
has vanished; it must not guess which inserted object belongs to that binding.

Only an authoritative `PlacementNoMutation` exception (transport guarantees
no write was started), supported by unchanged artifact revision, marker and
object IDs, can release an attempt fence after an error. Generic timeouts,
API errors, and any ambiguous failure keep the fence even if immediate
readback appears unchanged, because the remote mutation could complete late.
Success clears the fence only after verified receipt persistence; crashing
between those actions is recoverable only if the verified receipt, current
image readback, and complete recorded revision chain all validate. Invalid,
unreadable, cross-build, or duplicated receipt evidence fails closed.

Multiple consecutive images may advance the revision: recovery accepts
only an unbroken chain of **verified** later placements from the target
receipt's post-insertion revision to the current artifact revision. A
teacher edit, unreceipted insertion, or unknown revision transition is NOT
silently accepted. The completion backstop rejects unresolved attempt
fences, including optional-only builds. Before another remote mutation,
preflight also rejects attempt files from roles/artifacts absent from the
current placement scope. In-plan crash-after-receipt fences can still be
cleared after full receipt, revision-chain and live-object validation. A
manual reconciliation flow is still necessary for true orphans;
this code **never manufactures a placement receipt** from a missing marker.

No live Apps Script runtime is deployed here, and producer revisions under
PR #3651 are not modified. Independent QA and live execution authorization
remain separate.

## #3258 handoff

`placement_receipts/<idempotency_key>.json` records, per verified placement:
required visual roles and slots (bindings), selected assets (Asset IDs),
intended exact content identities, placement receipts (with artifact type/id,
marker, container, inserted element), and post-insertion revision -- plus the
current reconciled batch proof (`batch_proofs`, at most one per artifact).
Terminal artifact-content QA can answer: which roles were required, which assets were
selected, which revisions were intended, which receipts exist, which
artifact received them, and which reconciled batch proof binds them to the
observed final revision. Full semantic finality remains #3258's ownership.

## Live acceptance

Repository-side wiring plus injected-client acceptance is complete. Live
Docs/Slides execution requires the separately governed activation: deploy
the `VisualPlacementTransport` Apps Script as an API executable, grant
execution to the build identity, and configure `--placement-script-id`.
Until then, classification is IMPLEMENTED -- LIVE ACCEPTANCE PENDING.
