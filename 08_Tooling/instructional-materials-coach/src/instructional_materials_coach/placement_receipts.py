"""Durable placement-receipt store (#3257).

Persists verified visual-placement receipts per build idempotency key so
that:

- retry after a successful placement recovers the existing receipt instead
  of inserting the image again (#3252 idempotency);
- retry after a partial multi-image placement can distinguish already
  placed / not yet placed bindings;
- terminal artifact-content QA (#3258) can later ask which roles were
  required, which assets were selected, which exact content revisions were
  intended, which placement receipts exist, and which artifact received
  them.

Each record embeds the verified ``PlacementReceipt`` (#2087 contract,
state ``"verified"``) plus the envelope #3258 needs: the exact content
identity that was verified before insertion, the (role_id, slot_id)
binding, the source plan, the carried eligibility evidence, and the
transport that performed the insertion. Records are JSON files under
``<receipts_dir>/<idempotency_key>.json``; writes are atomic.

This store records placement evidence only. It is not an artifact
validator, a QA framework, or a provenance registry (#3258 owns those).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


RECEIPT_RECORD_CONTRACT = "visual-placement-receipt-v1"
# #3258: atomic reconciled batch proof bound to the ordered complete receipt
# set of one placement run (see reconcile_placement_batch). The proof's own
# artifact field is named ``batch_artifact_type`` to keep it distinct from
# the receipt envelope's ``artifact_type`` (and from #3643's
# ``VisualExpectation.artifact_type`` obligation-scope concept): different
# concepts, different names.
BATCH_PROOF_CONTRACT = "visual-placement-batch-proof-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def placement_record_path(receipts_dir: str | Path, idempotency_key: str) -> Path:
    key = str(idempotency_key or "").strip()
    if not key:
        raise ValueError("idempotency_key is required for the placement receipt store")
    if "/" in key or "\\" in key or ".." in key:
        raise ValueError("idempotency_key is not a safe receipt-store file name")
    return Path(receipts_dir) / f"{key}.json"


def load_placement_evidence(
    receipts_dir: str | Path, idempotency_key: str,
) -> tuple[tuple[dict[str, Any], ...], str | None]:
    """Read one receipt snapshot for QA and fingerprint its exact stored bytes.

    Missing evidence has an explicit stable identity (fresh QA determines
    whether absence is allowed). Unreadable or malformed evidence has no
    valid identity, so positive QA recovery must be refused.
    """
    path = placement_record_path(receipts_dir, idempotency_key)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return (), hashlib.sha256(b"placement-receipt:absent:v1").hexdigest()
    except OSError:
        return (), None
    # Use #3257's *complete* integrity validator on exactly these bytes.
    # Contract-only checks would miss malformed or duplicate unselected
    # records and could admit a false verified build.
    try:
        records = load_placement_records_strict(
            receipts_dir, idempotency_key, _raw=raw,
        )
    except PlacementStoreIntegrityError:
        return (), None
    return records, hashlib.sha256(raw).hexdigest()


def load_placement_records(receipts_dir: str | Path, idempotency_key: str) -> tuple[dict[str, Any], ...]:
    """Load all persisted placement records for one build, oldest first."""
    records, _ = load_placement_evidence(receipts_dir, idempotency_key)
    return records


def _load_payload(receipts_dir: str | Path, idempotency_key: str) -> dict[str, Any]:
    """Load the raw store payload (records plus any batch proofs).

    Best-effort: writers use this to preserve keys they do not own
    (notably ``batch_proofs``). Malformed stores yield ``{}``; the strict
    loader remains the fail-closed gate for every read that trusts
    evidence.
    """
    path = placement_record_path(receipts_dir, idempotency_key)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def append_placement_record(
    receipts_dir: str | Path,
    idempotency_key: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Append one verified placement record; returns the stored record."""
    stored = dict(record)
    stored["contract_version"] = RECEIPT_RECORD_CONTRACT
    stored["idempotency_key"] = str(idempotency_key)
    stored.setdefault("recorded_at", _utc_now())
    records = list(load_placement_records(receipts_dir, idempotency_key))
    # The same (role, slot, artifact, content identity) must never be
    # recorded twice: a second verified placement for an identical binding
    # is a duplicate-insertion signal, not a second receipt.
    identity = (
        stored.get("role_id"),
        stored.get("slot_id"),
        stored.get("artifact_type"),
        stored.get("artifact_id"),
        _canonical_json(stored.get("content_identity")),
    )
    for existing in records:
        existing_identity = (
            existing.get("role_id"),
            existing.get("slot_id"),
            existing.get("artifact_type"),
            existing.get("artifact_id"),
            _canonical_json(existing.get("content_identity")),
        )
        if existing_identity == identity and existing.get("state") == "verified":
            raise ValueError(
                "placement receipt store refuses a duplicate verified receipt for "
                f"role={stored.get('role_id')} slot={stored.get('slot_id')} "
                f"artifact={stored.get('artifact_type')}:{stored.get('artifact_id')}"
            )
    records.append(stored)
    path = placement_record_path(receipts_dir, idempotency_key)
    # Preserve any reconciled batch proofs already in the payload: appending
    # a record must never drop proof evidence. (The strict loader above
    # already failed closed on a malformed store, so _load_payload cannot
    # resurrect untrusted bytes here.)
    payload = _load_payload(receipts_dir, idempotency_key)
    payload["idempotency_key"] = str(idempotency_key)
    payload["records"] = records
    _write_atomic(path, payload)
    return stored


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def find_verified_record(
    records: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    role_id: str,
    slot_id: str,
    artifact_type: str,
    artifact_id: str,
    content_identity: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Recover the verified receipt for an identical binding, if one exists.

    Identity covers role, slot, artifact, AND the exact content identity:
    a receipt for a different revision of the same asset never satisfies
    recovery -- a stale revision must be re-placed (or fail closed), never
    silently accepted.
    """
    wanted_identity = _canonical_json(dict(content_identity) if content_identity else None)
    for record in records:
        if record.get("state") != "verified":
            continue
        if record.get("contract_version") != RECEIPT_RECORD_CONTRACT:
            continue
        if (
            record.get("role_id") == role_id
            and str(record.get("slot_id")) == str(slot_id)
            and record.get("artifact_type") == artifact_type
            and record.get("artifact_id") == artifact_id
            and _canonical_json(record.get("content_identity")) == wanted_identity
        ):
            return record
    return None


def build_placement_record(
    *,
    receipt: Mapping[str, Any],
    content_identity: Mapping[str, Any],
    slot_id: str,
    source_plan_id: str,
    required: bool,
    eligibility_evidence: Mapping[str, Any] | None,
    transport_name: str,
    post_insertion_revision: str,
) -> dict[str, Any]:
    """Assemble the persisted record envelope around a verified receipt."""
    return {
        "asset_id": receipt.get("asset_id"),
        "drive_file_id": receipt.get("drive_file_id"),
        "role_id": receipt.get("role_id"),
        "slot_id": str(slot_id),
        "artifact_type": receipt.get("artifact_type"),
        "artifact_id": receipt.get("artifact_id"),
        "artifact_revision_id": receipt.get("artifact_revision_id"),
        "marker": receipt.get("marker"),
        "container_id": receipt.get("container_id"),
        "inserted_element_id": receipt.get("inserted_element_id"),
        "state": receipt.get("state"),
        "content_identity": dict(content_identity),
        "source_plan_id": source_plan_id,
        "required": bool(required),
        "eligibility_evidence": dict(eligibility_evidence) if isinstance(eligibility_evidence, Mapping) else None,
        "transport": transport_name,
        "post_insertion_revision_id": post_insertion_revision,
        "placed_at": _utc_now(),
    }


# #3257 Phase 2: a transport can mutate an artifact and fail before a verified
# receipt is durably recorded. Atomically claim the exact (build, artifact,
# role, slot) BEFORE the external call; an interrupted process leaves a
# durable uncertainty fence, not permission to insert again.
# The file is intentionally separate from the verified-receipt ledger so that
# terminal QA and the v1 receipt contract still see exactly the same records.

class PlacementStoreIntegrityError(ValueError):
    """Receipt/attempt evidence is malformed; callers must fail closed."""


def load_placement_records_strict(
    receipts_dir: str | Path, idempotency_key: str, *, _raw: bytes | None = None,
) -> tuple[dict[str, Any], ...]:
    """Validate the complete receipt envelope before trusting ANY recovery.

    Keep the original permissive reader for legacy inspection callers; only
    recovery and its completion backstop require this strict boundary.
    """
    path = placement_record_path(receipts_dir, idempotency_key)
    if _raw is None:
        if not path.exists():
            return ()
        try:
            _raw = path.read_bytes()
        except OSError as exc:
            raise PlacementStoreIntegrityError('placement-receipt-store-invalid: unreadable JSON') from exc
    try:
        payload = json.loads(_raw)
    except (ValueError, UnicodeError) as exc:
        raise PlacementStoreIntegrityError('placement-receipt-store-invalid: unreadable or malformed JSON') from exc
    if (not isinstance(payload, dict) or payload.get('idempotency_key') != str(idempotency_key)
            or not isinstance(payload.get('records'), list)):
        raise PlacementStoreIntegrityError('placement-receipt-store-invalid: invalid envelope or build identity')
    records = payload['records']
    identities = set()
    physical_elements = set()
    for record in records:
        if not isinstance(record, dict) or record.get('idempotency_key') != str(idempotency_key):
            raise PlacementStoreIntegrityError('placement-receipt-store-invalid: invalid receipt item identity')
        if record.get('contract_version') != RECEIPT_RECORD_CONTRACT or record.get('state') != 'verified':
            raise PlacementStoreIntegrityError('placement-receipt-store-invalid: unknown contract or unverified item')
        for key in ('asset_id','drive_file_id','role_id','slot_id','artifact_type','artifact_id',
                    'artifact_revision_id','container_id','inserted_element_id',
                    'post_insertion_revision_id','source_plan_id'):
            if not isinstance(record.get(key), str) or not record[key]:
                raise PlacementStoreIntegrityError('placement-receipt-store-invalid: missing '+key)
        if not isinstance(record.get('content_identity'), dict):
            raise PlacementStoreIntegrityError('placement-receipt-store-invalid: malformed content identity')
        # Enforce receipt domains for every record, including abandoned or
        # now-unselected roles; a syntactically valid foreign type is not proof.
        if record['artifact_type'] not in ('docs', 'slides'):
            raise PlacementStoreIntegrityError('placement-receipt-store-invalid: unsupported artifact type')
        if not isinstance(record.get('required'), bool):
            raise PlacementStoreIntegrityError('placement-receipt-store-invalid: invalid required flag')
        # There is only one legal physical placement for a role/slot in an
        # artifact per idempotency key, even when bytes or asset ID differ.
        identity = (record['artifact_type'],record['artifact_id'],record['role_id'],str(record['slot_id']))
        if identity in identities:
            raise PlacementStoreIntegrityError('placement-receipt-store-invalid: duplicate/conflicting placement receipts')
        identities.add(identity)
        # Roles may reuse approved ASSET BYTES, but different role/slots must
        # not claim the same persisted physical image element in one artifact.
        # Docs and Slides (and distinct file IDs) have independent namespaces.
        physical = (record['artifact_type'], record['artifact_id'], record['inserted_element_id'])
        if physical in physical_elements:
            raise PlacementStoreIntegrityError('placement-receipt-store-invalid: inserted element claimed by multiple placements')
        physical_elements.add(physical)
    return tuple(records)


def _placement_attempt_dir(receipts_dir: str | Path, idempotency_key: str) -> Path:
    """Build-specific, bounded-length attempt directory (Windows MAX_PATH).

    The digest retains the build boundary without embedding its 64-character
    key in the directory name. No two builds intentionally share fences.
    """
    import hashlib
    placement_record_path(receipts_dir, idempotency_key)  # Validate key.
    build_digest = hashlib.sha256(str(idempotency_key).encode('utf-8')).hexdigest()[:24]
    return Path(receipts_dir) / ('.attempts-' + build_digest)


def placement_attempt_path(
    receipts_dir: str | Path, idempotency_key: str,
    *, artifact_type: str, artifact_id: str, role_id: str, slot_id: str,
) -> Path:
    import hashlib
    identity = _canonical_json([artifact_type, artifact_id, role_id, str(slot_id)])
    digest = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:48]
    return _placement_attempt_dir(receipts_dir, idempotency_key) / (digest + '.json')


def load_placement_attempt(
    receipts_dir: str | Path, idempotency_key: str,
    *, artifact_type: str, artifact_id: str, role_id: str, slot_id: str,
) -> dict[str, Any] | None:
    path = placement_attempt_path(receipts_dir,idempotency_key,artifact_type=artifact_type,
                                  artifact_id=artifact_id,role_id=role_id,slot_id=slot_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, ValueError, UnicodeError) as exc:
        raise PlacementStoreIntegrityError('placement-attempt-invalid: unreadable/malformed attempt') from exc
    required = {'idempotency_key':idempotency_key,'artifact_type':artifact_type,
                'artifact_id':artifact_id,'role_id':role_id,'slot_id':str(slot_id),
                'state':'in-flight'}
    if not isinstance(payload,dict) or any(payload.get(k) != v for k,v in required.items()):
        raise PlacementStoreIntegrityError('placement-attempt-invalid: mismatched attempt identity')
    for key in ('asset_id','drive_file_id','source_plan_id','artifact_revision_id',
                'marker','container_id'):
        if not isinstance(payload.get(key),str) or not payload[key]:
            raise PlacementStoreIntegrityError('placement-attempt-invalid: missing '+key)
    if not isinstance(payload.get('content_identity'),dict):
        raise PlacementStoreIntegrityError('placement-attempt-invalid: malformed content identity')
    return payload


def begin_placement_attempt(receipts_dir: str | Path, idempotency_key: str, intent: Mapping[str, Any]) -> None:
    """Exclusive pre-write fence: existence means uncertainty until reconciled."""
    path = placement_attempt_path(receipts_dir,idempotency_key,
        artifact_type=str(intent['artifact_type']),artifact_id=str(intent['artifact_id']),
        role_id=str(intent['role_id']),slot_id=str(intent['slot_id']))
    path.parent.mkdir(parents=True,exist_ok=True)
    payload = dict(intent)
    payload['idempotency_key'] = str(idempotency_key)
    payload['state'] = 'in-flight'
    try:
        # Exclusive create prevents duplicate concurrent claims. An interrupted
        # JSON write leaves an INVALID fence which also fails closed on retry.
        with path.open('x',encoding='utf-8') as handle:
            json.dump(payload,handle,sort_keys=True)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise PlacementStoreIntegrityError('placement-reconciliation-required: existing attempt fence') from exc


def clear_placement_attempt(receipts_dir: str | Path, idempotency_key: str, intent: Mapping[str, Any]) -> None:
    """Only clear an exactly matching fence after a proven safe outcome."""
    actual = load_placement_attempt(receipts_dir,idempotency_key,
        artifact_type=str(intent['artifact_type']),artifact_id=str(intent['artifact_id']),
        role_id=str(intent['role_id']),slot_id=str(intent['slot_id']))
    if actual is None or actual != dict(intent, idempotency_key=str(idempotency_key), state='in-flight'):
        raise PlacementStoreIntegrityError('placement-attempt-invalid: cannot clear mismatched fence')
    path = placement_attempt_path(receipts_dir,idempotency_key,
        artifact_type=str(intent['artifact_type']),artifact_id=str(intent['artifact_id']),
        role_id=str(intent['role_id']),slot_id=str(intent['slot_id']))
    path.unlink()


def assert_no_unresolved_placement_attempts(
    receipts_dir: str | Path,
    idempotency_key: str,
    *,
    permitted_for_recovery: frozenset[Path] = frozenset(),
) -> None:
    """Fail closed on any attempt outside the exactly permitted recovery set.

    Normal completion permits none. Placement preflight permits only paths
    for current artifact bindings: the caller must still verify those saved
    attempts and their receipts before using or clearing the fence.
    """
    directory = _placement_attempt_dir(receipts_dir, idempotency_key)
    try:
        if not directory.exists():
            return
        if not directory.is_dir():
            raise PlacementStoreIntegrityError('placement-attempt-invalid: journal path is not a directory')
        for item in directory.iterdir():
            if not item.is_file() or item not in permitted_for_recovery:
                raise PlacementStoreIntegrityError(
                    'placement-reconciliation-required: unresolved insertion attempt '
                    'outside the verified current recovery scope'
                )
    except OSError as exc:
        raise PlacementStoreIntegrityError('placement-attempt-invalid: cannot inspect journal') from exc


# ---------------------------------------------------------------------------
# Reconciled batch proofs (#3258)
# ---------------------------------------------------------------------------
# Sequential genuine insertions each advance the artifact revision, so the
# original per-insertion receipts legitimately disagree with the final
# revision. The receipts are append-only and are NEVER rewritten to the
# final revision. Instead, a completed placement run reconciles its ordered
# complete receipt set against one current artifact snapshot and persists
# this atomic batch proof, bound to:
#   - the ordered complete receipt set (role/slot/artifact/asset/content
#     identity/inserted element/original per-insertion revision),
#   - exact asset/content and element identities,
#   - artifact and build (idempotency key) identity,
#   - the observed final revision,
#   - verified per-insertion mutation continuity (before/after snapshots),
#   - a tamper-evident proof fingerprint that terminal QA recomputes when
#     it consumes the proof.
# The proof lives in the same store file as the receipts, so terminal QA's
# byte-identity recovery evidence (load_placement_evidence) automatically
# invalidates cached verified QA when a proof is added, removed, or
# altered. Terminal QA consumes the proof for members it revalidates; a
# missing (when required), conflicting, or tampered proof fails closed
# for manual review, never verifies.


_BATCH_PROOF_MEMBER_FIELDS = (
    "role_id",
    "slot_id",
    # Proof-side artifact field, deliberately distinct from the receipt
    # envelope's "artifact_type" (see BATCH_PROOF_CONTRACT comment).
    "batch_artifact_type",
    "artifact_id",
    "asset_id",
    "drive_file_id",
    "content_identity",
    "inserted_element_id",
    "post_insertion_revision_id",
    "member_source",
)


def batch_proof_fingerprint(proof: Mapping[str, Any]) -> str:
    """Tamper-evident fingerprint over the proof's semantic content.

    Covers everything except ``proof_fingerprint`` itself and the
    non-semantic ``reconciled_at`` timestamp. Terminal QA recomputes this
    (never trusting the stored field) when it consumes a proof.
    """
    payload = {
        key: value for key, value in dict(proof).items()
        if key not in ("proof_fingerprint", "reconciled_at")
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


# Fields terminal QA's verification logic actually consumes: a subset of
# _BATCH_PROOF_MEMBER_FIELDS. ``drive_file_id`` is producer-required by
# reconcile_placement_batch but never read by verification, so a
# hand-attested proof without it (e.g. the #3566 Day-1 regression
# fixture) remains verifiable. The producer still enforces the full set
# at write time.
_BATCH_PROOF_CONSUMER_FIELDS = tuple(
    field for field in _BATCH_PROOF_MEMBER_FIELDS if field != "drive_file_id"
)


def validate_batch_proof_structure(proof: Any) -> tuple[str, ...]:
    """Structural validation for a reconciled batch proof (consumer gate).

    Returns a tuple of human-readable issue strings; an empty tuple means
    the proof is structurally valid. Mirrors the producer-side invariants
    enforced by :func:`reconcile_placement_batch` for the fields terminal
    QA actually verifies (see ``_BATCH_PROOF_CONSUMER_FIELDS``):
    ``ordered_members`` is a non-empty list of mappings carrying every
    consumer-required field (non-empty strings, non-empty mapping for
    ``content_identity``), a valid ``member_source``, and no duplicate
    ``(role_id, slot_id)`` keys; ``insertion_continuity`` is a list of
    mappings.

    Consumers must call this BEFORE iterating ``ordered_members``,
    fingerprinting, or membership reconciliation: malformed evidence must
    fail closed, never crash iteration and never be silently skipped.
    """
    if not isinstance(proof, Mapping):
        return ("batch proof is not a mapping",)
    issues: list[str] = []
    members = proof.get("ordered_members")
    if not isinstance(members, (list, tuple)) or not members:
        issues.append("ordered_members must be a non-empty list")
    else:
        seen: set[tuple[str, str]] = set()
        for index, member in enumerate(members):
            label = f"ordered_members[{index}]"
            if not isinstance(member, Mapping):
                issues.append(f"{label} is not a mapping")
                continue
            for field in _BATCH_PROOF_CONSUMER_FIELDS:
                value = member.get(field)
                if field == "content_identity":
                    if not isinstance(value, Mapping) or not value:
                        issues.append(f"{label} is missing {field}")
                    continue
                if not isinstance(value, str) or not value.strip():
                    issues.append(f"{label} is missing {field}")
            if member.get("member_source") not in ("placed", "recovered"):
                issues.append(f"{label} has invalid member_source")
            key = (str(member.get("role_id")), str(member.get("slot_id")))
            if key in seen:
                issues.append(
                    f"duplicate proof member for role={key[0]} slot={key[1]}"
                )
            seen.add(key)
    continuity = proof.get("insertion_continuity")
    if not isinstance(continuity, (list, tuple)):
        issues.append("insertion_continuity must be a list")
    else:
        for index, entry in enumerate(continuity):
            if not isinstance(entry, Mapping):
                issues.append(f"insertion_continuity[{index}] is not a mapping")
    return tuple(issues)


def load_batch_proofs(receipts_dir: str | Path, idempotency_key: str) -> tuple[dict[str, Any], ...]:
    """Load all reconciled batch proofs for one build, oldest first."""
    proofs = _load_payload(receipts_dir, idempotency_key).get("batch_proofs")
    if not isinstance(proofs, list):
        return ()
    return tuple(
        proof for proof in proofs
        if isinstance(proof, dict) and proof.get("proof_contract") == BATCH_PROOF_CONTRACT
    )


def load_receipt_store_snapshot(
    receipts_dir: str | Path, idempotency_key: str,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...], str | None]:
    """Read the receipt store file ONCE; derive records, proofs, and hash.

    ``load_placement_evidence()`` and ``load_batch_proofs()`` each read the
    store file independently, so a writer landing between the two reads
    mixes receipts from one snapshot with proofs from another while the
    evidence hash attests only to the receipts (#3258 P1-3). Terminal QA
    consumes this single-snapshot loader so records, proofs, and the
    evidence hash always describe the same bytes. The other loaders stay
    available for callers that need only one facet; valid proofs keep the
    exact ``load_batch_proofs`` contract (dict + proof contract filter).
    """
    path = placement_record_path(receipts_dir, idempotency_key)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return (), (), hashlib.sha256(b"placement-receipt:absent:v1").hexdigest()
    except OSError:
        return (), (), None
    try:
        payload = json.loads(raw)
    except ValueError:
        return (), (), None
    if not isinstance(payload, dict):
        return (), (), None
    # Same strict gate and byte-identity hash as load_placement_evidence,
    # over exactly these bytes.
    try:
        records = load_placement_records_strict(
            receipts_dir, idempotency_key, _raw=raw,
        )
    except PlacementStoreIntegrityError:
        return (), (), None
    proofs_raw = payload.get("batch_proofs")
    proofs: tuple[dict[str, Any], ...] = ()
    if isinstance(proofs_raw, list):
        proofs = tuple(
            proof for proof in proofs_raw
            if isinstance(proof, dict)
            and proof.get("proof_contract") == BATCH_PROOF_CONTRACT
        )
    return records, proofs, hashlib.sha256(raw).hexdigest()


def reconcile_placement_batch(
    *,
    receipts_dir: str | Path,
    idempotency_key: str,
    batch_artifact_type: str,
    artifact_id: str,
    ordered_members: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    insertion_continuity: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    initial_revision_id: str,
    final_revision_id: str,
) -> dict[str, Any]:
    """Persist one atomic reconciled batch proof; returns the stored proof.

    ``ordered_members`` is the complete ordered receipt set for this run
    (bindings placed or recovered here), each carrying the ORIGINAL
    per-insertion ``post_insertion_revision_id``. ``insertion_continuity``
    holds the verified before/after evidence for the insertions performed
    in this run, in insertion order. The continuity chain must link:
    first pre-revision == initial, each post == next pre, last post ==
    final (or final == initial when nothing was inserted).
    """
    kind = str(batch_artifact_type or "").strip().lower()
    if kind not in ("docs", "slides"):
        raise ValueError(f"reconcile_placement_batch: unsupported batch artifact type {batch_artifact_type!r}")
    target_artifact = str(artifact_id or "").strip()
    if not target_artifact:
        raise ValueError("reconcile_placement_batch: artifact_id is required")
    members = [dict(member) for member in ordered_members or ()]
    if not members:
        raise ValueError("reconcile_placement_batch: ordered_members must not be empty")
    seen: set[tuple[str, str]] = set()
    for member in members:
        for field in _BATCH_PROOF_MEMBER_FIELDS:
            if field == "content_identity":
                if not isinstance(member.get(field), Mapping) or not member[field]:
                    raise ValueError(f"reconcile_placement_batch: member is missing {field}")
                continue
            value = member.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"reconcile_placement_batch: member is missing {field}")
        if member.get("member_source") not in ("placed", "recovered"):
            raise ValueError("reconcile_placement_batch: member_source must be 'placed' or 'recovered'")
        key = (str(member["role_id"]), str(member["slot_id"]))
        if key in seen:
            raise ValueError(f"reconcile_placement_batch: duplicate member for role={key[0]} slot={key[1]}")
        seen.add(key)
    continuity = [dict(entry) for entry in insertion_continuity or ()]
    placed_keys = {key for key, member in
                   (((str(m["role_id"]), str(m["slot_id"])), m) for m in members)
                   if member.get("member_source") == "placed"}
    for entry in continuity:
        for field in ("role_id", "slot_id", "inserted_element_id", "pre_revision_id", "post_revision_id"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"reconcile_placement_batch: continuity entry is missing {field}")
        entry_key = (str(entry["role_id"]), str(entry["slot_id"]))
        if entry_key not in placed_keys:
            raise ValueError(
                "reconcile_placement_batch: continuity entry for "
                f"role={entry_key[0]} slot={entry_key[1]} has no 'placed' member"
            )
        placed_member = next(m for m in members
                             if (str(m["role_id"]), str(m["slot_id"])) == entry_key)
        if str(placed_member.get("inserted_element_id")) != str(entry["inserted_element_id"]):
            raise ValueError(
                "reconcile_placement_batch: continuity entry element id does not "
                "match its placed member"
            )
    if continuity:
        if str(continuity[0].get("pre_revision_id")) != str(initial_revision_id):
            raise ValueError("reconcile_placement_batch: first pre-revision != initial revision")
        for previous, current in zip(continuity, continuity[1:]):
            if str(current.get("pre_revision_id")) != str(previous.get("post_revision_id")):
                raise ValueError("reconcile_placement_batch: insertion chain is broken")
        if str(continuity[-1].get("post_revision_id")) != str(final_revision_id):
            raise ValueError("reconcile_placement_batch: last post-revision != final revision")
    elif str(initial_revision_id) != str(final_revision_id):
        raise ValueError("reconcile_placement_batch: final != initial with no insertions")
    proof: dict[str, Any] = {
        "proof_contract": BATCH_PROOF_CONTRACT,
        "idempotency_key": str(idempotency_key),
        "batch_artifact_type": kind,
        "artifact_id": target_artifact,
        "initial_revision_id": str(initial_revision_id),
        "final_revision_id": str(final_revision_id),
        "ordered_members": members,
        "insertion_continuity": continuity,
        "reconciled_at": _utc_now(),
    }
    proof["proof_fingerprint"] = batch_proof_fingerprint(proof)
    path = placement_record_path(receipts_dir, idempotency_key)
    payload = _load_payload(receipts_dir, idempotency_key)
    payload["idempotency_key"] = str(idempotency_key)
    # The proof is the CURRENT reconciled attestation for one artifact: a
    # new reconciliation supersedes the previous proof for the same
    # artifact (the append-only receipt history is preserved untouched).
    # Proofs for other artifacts sharing this build's store are kept. Two
    # proofs ever claiming the same artifact is conflicting evidence, not
    # history -- terminal QA fails it closed.
    proofs = [
        existing for existing in (payload.get("batch_proofs") or [])
        if isinstance(existing, dict)
        and not (
            existing.get("batch_artifact_type") == kind
            and str(existing.get("artifact_id")) == target_artifact
        )
    ]
    proofs.append(proof)
    payload["batch_proofs"] = proofs
    _write_atomic(path, payload)
    return proof
