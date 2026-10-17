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
# set of one placement run (see reconcile_placement_batch).
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


def load_placement_records(receipts_dir: str | Path, idempotency_key: str) -> tuple[dict[str, Any], ...]:
    """Load all persisted placement records for one build, oldest first."""
    records = _load_payload(receipts_dir, idempotency_key).get("records")
    if not isinstance(records, list):
        return ()
    return tuple(item for item in records if isinstance(item, dict))


def _load_payload(receipts_dir: str | Path, idempotency_key: str) -> dict[str, Any]:
    """Load the raw store payload (records plus any batch proofs)."""
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
    # a record must never drop proof evidence.
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
#   - a tamper-evident proof fingerprint that terminal QA also binds into
#     its recovery identity (the recovery cache fingerprint).
# Terminal QA consumes the proof for members it revalidates; a missing,
# conflicting, or tampered proof is MANUAL REVIEW, never verification.


_BATCH_PROOF_MEMBER_FIELDS = (
    "role_id",
    "slot_id",
    "artifact_type",
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
    non-semantic ``reconciled_at`` timestamp.
    """
    payload = {
        key: value for key, value in dict(proof).items()
        if key not in ("proof_fingerprint", "reconciled_at")
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def receipt_set_fingerprint(records: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> str:
    """Fingerprint over the ordered receipt set for recovery identity.

    Any membership or content change in the receipt set changes this
    fingerprint, so terminal QA recovery cannot reuse cached verified QA
    after the receipt set changed.
    """
    return hashlib.sha256(
        _canonical_json([dict(record) for record in records or ()]).encode("utf-8")
    ).hexdigest()


def batch_proofs_fingerprint(proofs: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None) -> str:
    """Fingerprint over the ordered batch proofs for recovery identity.

    Hashes the RECOMPUTED proof fingerprints (semantic content), never the
    proofs' self-claimed ``proof_fingerprint`` fields: tampering with a
    proof's members changes this fingerprint even when the stored field is
    left untouched, so terminal QA recovery cannot reuse cached verified
    QA after a proof change.
    """
    fingerprints = [batch_proof_fingerprint(proof) for proof in proofs or ()]
    return hashlib.sha256(_canonical_json(fingerprints).encode("utf-8")).hexdigest()


def load_batch_proofs(receipts_dir: str | Path, idempotency_key: str) -> tuple[dict[str, Any], ...]:
    """Load all reconciled batch proofs for one build, oldest first."""
    proofs = _load_payload(receipts_dir, idempotency_key).get("batch_proofs")
    if not isinstance(proofs, list):
        return ()
    return tuple(
        proof for proof in proofs
        if isinstance(proof, dict) and proof.get("proof_contract") == BATCH_PROOF_CONTRACT
    )


def reconcile_placement_batch(
    *,
    receipts_dir: str | Path,
    idempotency_key: str,
    artifact_type: str,
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
    kind = str(artifact_type or "").strip().lower()
    if kind not in ("docs", "slides"):
        raise ValueError(f"reconcile_placement_batch: unsupported artifact type {artifact_type!r}")
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
        "artifact_type": kind,
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
            existing.get("artifact_type") == kind
            and str(existing.get("artifact_id")) == target_artifact
        )
    ]
    proofs.append(proof)
    payload["batch_proofs"] = proofs
    _write_atomic(path, payload)
    return proof
