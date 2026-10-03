# Asset Content Identity Contract (#3256)

**Owner:** #3256 (Lane D). **Consumers:** #3252 (persistence/continuation/idempotency), #3254 (eligibility evidence), #3257 (placement), #3258 (artifact QA).

## Invariant

An approved, selected, or placed visual asset is bound to:

1. a **stable logical asset identity** independent of mutable references, and
2. an **exact content identity** (hash and/or revision), verified at selection,
   slot resolution, and placement.

A content mismatch fails closed per asset as an explicit non-absence state.
It never becomes absence and never authorizes a generation handoff.

## Canonical logical Asset ID

Issued by `instructional_workflow_contracts.reusable_visual_identity.issue_reusable_visual_identity`
(contract `governed-reusable-visual-identity-v1`):

- `asset_id`: `visual-asset-<24 hex>`; `stable_ref`: `visual-ref-<64 hex>`.
- The digest basis is **stable identity evidence only**: contract version,
  provider + Drive `file_id`, SHA-256 content fingerprint, source reference +
  source fingerprint, and lineage.
- **Excluded from the basis** (still required inputs, still reported on the
  issued identity, but not part of the digest): `exact_reference` (mutable URL
  text) and `evidence_reference` (mutable sync reference). Re-syncing
  identical bytes through a different reference or URL therefore preserves the
  asset identity; no `identity.conflict`.
- Identities minted before this basis change cannot reconcile under the new
  digest and surface as `identity.conflict` (manual review): re-issue them.

## Provider file identity

- `provider`: `"google-drive"`.
- `file_id`: the Drive file ID.
- `exact_reference`: the verified reference string (e.g. `drive:<file_id>` or
  the `webViewLink`) at issuance time. Informational only; never part of the
  identity digest.

## Exact content/revision identity

Model: `instructional_workflow_contracts.asset_content_identity`
(contract `governed-asset-content-identity-v1`):

```python
{
    "contract_version": "governed-asset-content-identity-v1",
    "source": "drive-sha256" | "drive-md5" | "drive-head-revision" | "local-hash",
    "algorithm": "sha256" | "md5" | "drive-revision",
    "value": "<hex digest or Drive revision id>",
}
```

**Canonical precedence (D7 decision):** Drive `sha256Checksum` > Drive
`md5Checksum` > Drive `headRevisionId` > locally computed SHA-256 over bytes
the caller holds. Every consumer derives the same identity from the same
metadata.

Drive metadata calls **must** request `md5Checksum`, `sha256Checksum`, and
`headRevisionId` (`drive_client.get_file_metadata` includes them).

## Provenance requirements

Identity issuance requires:

- `source_reference` + `source_fingerprint` (stable source identity; part of
  the digest basis),
- `evidence_reference` (the mutable sync/evidence pointer; required input,
  reported on the identity, excluded from the digest),
- `lineage.kind` in `{original, sanitized-derivative, rendition,
  superseding-version}` with predecessor identity for non-originals.

## Drift detection

Re-derive the current content identity from live Drive metadata
(`select_content_identity`) and compare it to the recorded one
(`verify_content_identity`):

| Outcome | Meaning | Disposition |
|---|---|---|
| `content-identity-match` | bytes unchanged | proceed |
| `content-identity-mismatch` | bytes changed after approval | fail closed per asset; explicit `content-identity-mismatch` |
| `content-identity-unverifiable` | no usable identity fields, or incomparable algorithms | fail closed per asset; distinct non-absence state |
| `content-identity-not-recorded` | no expected identity supplied | caller-defined (slot resolution passes through; placement requires binding) |

Drive lookup failures are classified separately and are also distinct:
`not-found` (deleted) vs `no-access` (permission gap) vs `lookup-failed`.
None of these is absence; none authorizes generation.

Verification points:

- **Selection:** the CLI resolves expected identities from the governed plan's
  selected candidates (`asset_reference.content_fingerprint`) before any
  connected build step.
- **Slot resolution** (`asset_slot_resolution.resolve_asset_slots`): accepts
  `expected_content_identities`; per-slot outcomes in `slot_outcomes`,
  mismatches listed in `content_identity_mismatches`.
- **Placement** (`visual_placement`): `PlacementRequest` must carry a valid
  `content_identity`; `verify_request_content_identity` checks it against
  fresh metadata immediately before insertion; the receipt must reconstruct it.

## How legitimate revisions advance identity

A provider-side edit produces a new hash and/or new `headRevisionId` while the
logical `asset_id`/`stable_ref` is unchanged (the file is the same; the bytes
are not). Consumers must treat the new content identity as **different
selected content**:

- Re-verify; on `content-identity-mismatch`, fail closed and route for
  re-approval. Do not silently accept the new bytes under the old approval.
- A rendition or edited copy is a new lineage (`rendition` /
  `superseding-version`) with its own identity, linked via predecessor fields.
- Logical identity answers "which asset"; content identity answers "which
  exact bytes". Never substitute one for the other.

## What this contract does not do

- No Notion or Drive writes. The identity is recorded in the repository
  manifest and governed evidence only.
- No deduplication of live records. Duplicate Drive IDs surface as
  `DUPLICATE_ID` in reconciliation; duplicate titles are reported read-only
  by `visual_asset_sync.reconcile.find_duplicate_titles`.
- Placement runtime belongs to #3257; terminal artifact QA to #3258.
