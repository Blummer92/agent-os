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
    _write_atomic(path, {"idempotency_key": str(idempotency_key), "records": records})
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
