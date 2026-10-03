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


def load_placement_records(receipts_dir: str | Path, idempotency_key: str) -> tuple[dict[str, Any], ...]:
    """Load all persisted placement records for one build, oldest first."""
    path = placement_record_path(receipts_dir, idempotency_key)
    if not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return ()
    return tuple(item for item in records if isinstance(item, dict))


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
