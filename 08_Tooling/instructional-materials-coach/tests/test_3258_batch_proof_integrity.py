"""#3258 P1 repairs: batch-proof structural, membership, and snapshot integrity.

Drives the real ``run_terminal_qa()`` (and the real producer) against
genuine 2-image Docs placements whose persisted store JSON is then
mutated, reproducing the three independent-review P1 findings as
fail-closed behavior:

- P1-1 (malformed batch proof): structural validation runs BEFORE any
  member iteration, fingerprint check, or membership reconciliation. A
  non-list ``ordered_members``, non-mapping members, missing/empty
  required member fields, an invalid ``member_source``, duplicate
  (role, slot) members, or malformed ``insertion_continuity`` all yield
  ``invalid`` / ``qa-batch-proof-invalid`` -- never an uncaught
  ``TypeError``, never silent skips, never a verified empty member map.
- P1-2 (exact membership): bidirectional correspondence between the
  verified receipt set and the reconciled proof's member set. A shrunken
  proof with a corrected fingerprint, an unexpected extra member, or a
  changed fingerprint all fail closed; the per-receipt revision-chain
  fallback no longer admits visuals outside a verified proof.
- P1-3 (two-read race): ``run_terminal_qa`` derives records, proofs, and
  the evidence hash from ONE store read (``load_receipt_store_snapshot``),
  so mixed snapshots can never verify. Regression tests simulate a
  writer landing around the single read and prove the verdict always
  matches the snapshot actually consumed.

D3 duplicate-content determination (2026-10-19, no code change): the
governed policy (``docs/terminal-qa-contract.md`` "Text proof";
``ContentExpectation.max_occurrences``) makes duplication policing
OPT-IN per expectation -- ``qa-content-duplicated`` fires only when a
governed ``max_occurrences`` is set and exceeded. With no
``max_occurrences``, repeated content is NOT a failure. This is
intentional: the governed plan opts specific expectations into
duplication policing, and terminal QA must not invent a blanket rule.
The tests below establish exactly this governed behavior.

All external interaction uses injected fakes; no live Docs/Slides/Drive
mutation occurs in this suite.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_VERIFIED,
    ContentExpectation,
    TerminalQAExpectations,
    run_terminal_qa,
)
from instructional_materials_coach.connected_visual_placement import (
    PlacementExecutionError,
    execute_artifact_visual_placements,
)
from instructional_materials_coach.placement_receipts import (
    batch_proof_fingerprint,
    load_batch_proofs,
    load_placement_evidence,
    load_placement_records,
    load_receipt_store_snapshot,
    validate_batch_proof_structure,
)


# Reuse the #3257 suite's service fakes (injected, offline).
_FAKE_MODULE = Path(__file__).with_name("test_3257_connected_visual_placement.py")
_spec = importlib.util.spec_from_file_location("_p1r_fakes_3257", _FAKE_MODULE)
assert _spec is not None and _spec.loader is not None
_fakes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fakes)

KEY = "k" * 64


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _docs_env(n: int):
    """Build an offline docs world with n genuine marker paragraphs."""
    bindings = tuple(
        _fakes._binding(f"figure-{i}", asset_id=f"asset-{i}", drive_file_id=f"file-{i}")
        for i in range(n)
    )
    docs = _fakes.FakeDocsService()
    docs.add_document("doc-1", [f"{{{{visual:figure-{i}}}}}" for i in range(n)])
    drive = _fakes.FakeDriveService(
        {f"file-{i}": _fakes._drive_metadata(f"file-{i}") for i in range(n)}
    )
    transport = _fakes.FakePlacementTransport(docs=docs)
    return bindings, docs, drive, transport


def _place_docs(bindings, docs, drive, transport, receipts_dir, key=KEY):
    return execute_artifact_visual_placements(
        bindings=bindings,
        artifact_type="docs",
        artifact_id="doc-1",
        drive_service=drive,
        artifact_service=docs,
        transport=transport,
        receipts_dir=str(receipts_dir),
        idempotency_key=key,
    )


def _terminal_qa(bindings, docs, receipts_dir, key=KEY):
    expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key=key, visual_placements=bindings
    )
    slides = _fakes.FakeSlidesService()
    slides.add_presentation("slides-1", [], revision="r1")
    return run_terminal_qa(
        expectations=expectations,
        slides_service=slides,
        docs_service=docs,
        slides_file_id="slides-1",
        worksheet_file_id="doc-1",
        receipts_dir=str(receipts_dir),
        qa_evidence_dir=None,
    )


def _codes(report) -> list[str]:
    return [f.code for f in report.worksheet.findings]


def _store_path(receipts_dir, key=KEY) -> Path:
    return Path(receipts_dir) / f"{key}.json"


def _rewrite_store(receipts_dir, mutator, key=KEY) -> None:
    path = _store_path(receipts_dir, key)
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutator(payload)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _refix_proof_fingerprint(payload: dict[str, Any]) -> None:
    """Recompute proof_fingerprint over mutated proof content.

    Isolates structural/membership semantics from tamper detection: after
    mutation the proof is self-consistent again, so any rejection is about
    structure or membership, not the fingerprint check.
    """
    for proof in payload.get("batch_proofs", []):
        proof["proof_fingerprint"] = batch_proof_fingerprint(proof)


def _valid_two_image(tmp_path):
    """Genuine 2-image placement; returns (bindings, docs, receipts_dir)."""
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    bindings, docs, drive, transport = _docs_env(2)
    outcomes = _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert [o.status for o in outcomes] == ["placed", "placed"]
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert report.worksheet.state == QA_STATE_VERIFIED, _codes(report)
    return bindings, docs, receipts_dir


def _assert_proof_invalid(tmp_path, mutator, *, refix: bool = True) -> None:
    """Mutate the persisted proof, then prove fail-closed (no exception)."""
    bindings, docs, receipts_dir = _valid_two_image(tmp_path)

    def _m(payload: dict[str, Any]) -> None:
        mutator(payload["batch_proofs"][0])
        if refix:
            _refix_proof_fingerprint(payload)

    _rewrite_store(receipts_dir, _m)
    report = _terminal_qa(bindings, docs, receipts_dir)  # must not raise
    assert report.worksheet.state != QA_STATE_VERIFIED
    assert "qa-batch-proof-invalid" in _codes(report)


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------


def test_valid_two_image_batch_verifies(tmp_path):
    bindings, docs, receipts_dir = _valid_two_image(tmp_path)
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert report.worksheet.state == QA_STATE_VERIFIED
    assert _codes(report) == []


def test_single_receipt_placement_verifies_without_proof(tmp_path):
    """Single-receipt placements require no batch proof (unchanged)."""
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    bindings, docs, drive, transport = _docs_env(1)
    outcomes = _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert [o.status for o in outcomes] == ["placed"]
    # The producer persists a proof even for one binding; the point of this
    # control is the consumer side: a lone verified receipt still verifies.
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert report.worksheet.state == QA_STATE_VERIFIED, _codes(report)


# ---------------------------------------------------------------------------
# P1-1: malformed batch-proof structure fails closed
# ---------------------------------------------------------------------------


def test_ordered_members_non_iterable_fails_closed(tmp_path):
    _assert_proof_invalid(tmp_path, lambda p: p.update(ordered_members=5))


def test_ordered_members_string_with_valid_fingerprint_fails_closed(tmp_path):
    # RED bonus case: string members + corrected fingerprint used to verify
    # with an empty member map via the per-receipt fallback.
    _assert_proof_invalid(tmp_path, lambda p: p.update(ordered_members="ab"))


def test_ordered_members_missing_with_valid_fingerprint_fails_closed(tmp_path):
    # RED bonus case: a proof claiming nothing used to verify.

    def _m(proof: dict[str, Any]) -> None:
        del proof["ordered_members"]

    _assert_proof_invalid(tmp_path, _m)


def test_ordered_members_non_mapping_entries_fails_closed(tmp_path):
    _assert_proof_invalid(tmp_path, lambda p: p.update(ordered_members=[5, "x"]))


def test_member_missing_required_field_fails_closed(tmp_path):
    def _m(proof: dict[str, Any]) -> None:
        del proof["ordered_members"][0]["asset_id"]

    _assert_proof_invalid(tmp_path, _m)


def test_member_empty_required_field_fails_closed(tmp_path):
    def _m(proof: dict[str, Any]) -> None:
        proof["ordered_members"][0]["role_id"] = "  "

    _assert_proof_invalid(tmp_path, _m)


def test_member_malformed_content_identity_fails_closed(tmp_path):
    def _m(proof: dict[str, Any]) -> None:
        proof["ordered_members"][0]["content_identity"] = "not-a-mapping"

    _assert_proof_invalid(tmp_path, _m)


def test_member_invalid_member_source_fails_closed(tmp_path):
    def _m(proof: dict[str, Any]) -> None:
        proof["ordered_members"][0]["member_source"] = "bogus"

    _assert_proof_invalid(tmp_path, _m)


def test_insertion_continuity_malformed_fails_closed(tmp_path):
    _assert_proof_invalid(tmp_path, lambda p: p.update(insertion_continuity="nope"))


def test_insertion_continuity_non_mapping_entry_fails_closed(tmp_path):
    _assert_proof_invalid(tmp_path, lambda p: p.update(insertion_continuity=[7]))


def test_duplicate_proof_member_fails_closed(tmp_path):
    # P1-2(b3): duplicate (role,slot) used to collapse silently (last wins)
    # and verify with a corrected fingerprint.

    def _m(proof: dict[str, Any]) -> None:
        proof["ordered_members"].append(dict(proof["ordered_members"][0]))

    _assert_proof_invalid(tmp_path, _m)


def test_validate_batch_proof_structure_accepts_valid_proof(tmp_path):
    _, _, receipts_dir = _valid_two_image(tmp_path)
    (proof,) = load_batch_proofs(receipts_dir, KEY)
    assert validate_batch_proof_structure(proof) == ()


def test_validate_batch_proof_structure_rejects_garbage():
    assert validate_batch_proof_structure(5) != ()
    assert validate_batch_proof_structure(None) != ()
    assert validate_batch_proof_structure({}) != ()
    assert validate_batch_proof_structure({"ordered_members": []}) != ()


def test_consumer_tolerates_missing_drive_file_id(tmp_path):
    """drive_file_id is producer-required but never consumed by
    verification: a hand-attested proof without it (the #3566 Day-1
    fixture shape) remains verifiable."""
    bindings, docs, receipts_dir = _valid_two_image(tmp_path)

    def _m(payload: dict[str, Any]) -> None:
        for member in payload["batch_proofs"][0]["ordered_members"]:
            del member["drive_file_id"]
        _refix_proof_fingerprint(payload)

    _rewrite_store(receipts_dir, _m)
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert report.worksheet.state == QA_STATE_VERIFIED, _codes(report)


def test_producer_reconcile_rejects_malformed_prior_proof(tmp_path):
    """_reconcile_completed_batch fails closed on a corrupted prior proof."""
    bindings, docs, drive, transport = _docs_env(2)
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert len(load_batch_proofs(receipts_dir, KEY)) == 1

    def _m(payload: dict[str, Any]) -> None:
        payload["batch_proofs"][0]["ordered_members"] = 5

    _rewrite_store(receipts_dir, _m)
    with pytest.raises(PlacementExecutionError, match="placement-batch-unreconciled"):
        _place_docs(bindings, docs, drive, transport, receipts_dir)


# ---------------------------------------------------------------------------
# P1-2: exact bidirectional membership
# ---------------------------------------------------------------------------


def test_shrunk_proof_with_valid_fingerprint_fails_closed(tmp_path):
    """P1-2(b1): proof drops a member, receipts unchanged, fingerprint fixed.

    The dropped member's receipt used to be re-admitted by the permissive
    per-receipt revision-chain fallback -> VERIFIED. Now the receipts->proof
    direction fails closed.
    """

    def _m(proof: dict[str, Any]) -> None:
        proof["ordered_members"] = proof["ordered_members"][:1]

    _assert_proof_invalid(tmp_path, _m)


def test_receipt_deleted_proof_unchanged_fails_closed(tmp_path):
    """Direction (a): receipt removed while the proof still claims it."""

    def _m(payload: dict[str, Any]) -> None:
        payload["records"] = payload["records"][:1]

    bindings, docs, receipts_dir = _valid_two_image(tmp_path)
    _rewrite_store(receipts_dir, _m)
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert report.worksheet.state != QA_STATE_VERIFIED
    assert "qa-batch-proof-invalid" in _codes(report)


def test_changed_fingerprint_fails_closed(tmp_path):
    def _m(proof: dict[str, Any]) -> None:
        proof["proof_fingerprint"] = "0" * 64

    _assert_proof_invalid(tmp_path, _m, refix=False)


def test_unexpected_extra_member_fails_closed(tmp_path):
    """Proof claims a member with no matching stored receipt."""

    def _m(proof: dict[str, Any]) -> None:
        extra = dict(proof["ordered_members"][0])
        extra["role_id"] = "figure-9"
        extra["slot_id"] = "9"
        extra["asset_id"] = "asset-9"
        proof["ordered_members"].append(extra)

    _assert_proof_invalid(tmp_path, _m)


def test_swapped_member_content_identity_fails_closed(tmp_path):
    def _m(proof: dict[str, Any]) -> None:
        proof["ordered_members"][0]["content_identity"] = {"tampered": True}

    _assert_proof_invalid(tmp_path, _m)


def test_two_proofs_claiming_same_artifact_conflict(tmp_path):
    bindings, docs, receipts_dir = _valid_two_image(tmp_path)

    def _m(payload: dict[str, Any]) -> None:
        payload["batch_proofs"].append(dict(payload["batch_proofs"][0]))

    _rewrite_store(receipts_dir, _m)
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert report.worksheet.state != QA_STATE_VERIFIED
    assert "qa-batch-proof-conflict" in _codes(report)


# ---------------------------------------------------------------------------
# P1-3: single receipt-store snapshot
# ---------------------------------------------------------------------------


def test_snapshot_matches_legacy_loaders_on_static_store(tmp_path):
    """load_receipt_store_snapshot preserves the valid-proof contract."""
    _, _, receipts_dir = _valid_two_image(tmp_path)
    records, proofs, evidence_hash = load_receipt_store_snapshot(receipts_dir, KEY)
    assert records == load_placement_records(receipts_dir, KEY)
    assert proofs == load_batch_proofs(receipts_dir, KEY)
    assert evidence_hash == load_placement_evidence(receipts_dir, KEY)[1]
    assert len(proofs) == 1


def test_snapshot_absent_store(tmp_path):
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    records, proofs, evidence_hash = load_receipt_store_snapshot(
        receipts_dir, "no-such-key"
    )
    assert records == () and proofs == ()
    assert evidence_hash == load_placement_evidence(receipts_dir, "no-such-key")[1]


def test_snapshot_malformed_json_store_fails_closed(tmp_path):
    """Malformed store bytes: no exception, never verified."""
    bindings, docs, receipts_dir = _valid_two_image(tmp_path)
    _store_path(receipts_dir).write_bytes(b"not json{{{")
    report = _terminal_qa(bindings, docs, receipts_dir)  # must not raise
    assert report.worksheet.state != QA_STATE_VERIFIED


def _remove_proof_bytes(receipts_dir) -> tuple[bytes, bytes]:
    """Return (snapshot_a_no_proof, snapshot_b_with_proof); leave A on disk."""
    full = _store_path(receipts_dir).read_bytes()
    payload = json.loads(full.decode("utf-8"))
    assert payload.get("batch_proofs"), "seed must carry a proof"
    del payload["batch_proofs"]
    snap_a = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _store_path(receipts_dir).write_bytes(snap_a)
    return snap_a, full


def test_exactly_one_store_read_per_run(tmp_path, monkeypatch):
    bindings, docs, receipts_dir = _valid_two_image(tmp_path)
    store = _store_path(receipts_dir)
    real_read_bytes = Path.read_bytes
    reads: list[int] = []

    def _counting(self: Path) -> bytes:
        data = real_read_bytes(self)
        if self == store:
            reads.append(len(data))
        return data

    monkeypatch.setattr(Path, "read_bytes", _counting)
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert reads and len(reads) == 1, f"expected 1 store read, saw {len(reads)}"
    assert report.worksheet.state == QA_STATE_VERIFIED
    assert report.placement_evidence_hash == hashlib.sha256(store.read_bytes()).hexdigest()


def test_writer_before_single_read_is_self_consistent(tmp_path, monkeypatch):
    """Writer wins before the single read: VERIFIED only with a hash that
    attests to the proof-bearing snapshot actually consumed."""
    bindings, docs, receipts_dir = _valid_two_image(tmp_path)
    snap_a, snap_b = _remove_proof_bytes(receipts_dir)
    store = _store_path(receipts_dir)
    real_read_bytes = Path.read_bytes
    reads: list[int] = []

    def _racing(self: Path) -> bytes:
        if self == store:
            reads.append(1)
            store.write_bytes(snap_b)  # writer lands BEFORE the single read
            return snap_b
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _racing)
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert len(reads) == 1
    # The single read observed snapshot B (proof genuinely on disk at read
    # time): VERIFIED is legitimate and the hash binds exactly those bytes.
    assert report.worksheet.state == QA_STATE_VERIFIED
    assert report.placement_evidence_hash == hashlib.sha256(snap_b).hexdigest()
    assert report.placement_evidence_hash != hashlib.sha256(snap_a).hexdigest()


def test_writer_after_single_read_fails_closed(tmp_path, monkeypatch):
    """Writer lands after the single read: the proof-less snapshot consumed
    fails closed under the strict missing-proof rule; mixed evidence can
    never yield VERIFIED."""
    bindings, docs, receipts_dir = _valid_two_image(tmp_path)
    snap_a, snap_b = _remove_proof_bytes(receipts_dir)
    store = _store_path(receipts_dir)
    real_read_bytes = Path.read_bytes
    reads: list[int] = []

    def _racing(self: Path) -> bytes:
        if self == store:
            reads.append(1)
            data = real_read_bytes(self)  # snapshot A (no proof)
            store.write_bytes(snap_b)  # writer lands AFTER the single read
            return data
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _racing)
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert len(reads) == 1
    assert report.worksheet.state != QA_STATE_VERIFIED
    assert "qa-batch-proof-missing" in _codes(report)
    # The hash attests to the snapshot actually consumed (A), not to the
    # proof that arrived too late.
    assert report.placement_evidence_hash == hashlib.sha256(snap_a).hexdigest()
    # The P1-3 RED signature -- VERIFIED while the hash attests to
    # proof-less bytes -- is impossible.
    assert not (
        report.worksheet.state == QA_STATE_VERIFIED
        and report.placement_evidence_hash == hashlib.sha256(snap_a).hexdigest()
    )


# ---------------------------------------------------------------------------
# D3: duplicate-content policy is opt-in per expectation (no code change)
# ---------------------------------------------------------------------------


class _ContentDocsService:
    """Minimal docs fake for content-only QA (no visuals)."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    def add(self, doc_id: str, paragraphs: list[str], revision: str = "r1") -> None:
        self.docs[doc_id] = {"revisionId": revision, "paragraphs": list(paragraphs)}

    def documents(self):  # noqa: ANN202
        service = self

        class _Res:
            def get(self, *, documentId: str, fields: str | None = None):  # noqa: ANN202
                doc = service.docs[documentId]
                content = [
                    {"paragraph": {"elements": [{"textRun": {"content": t + "\n"}}]}}
                    for t in doc["paragraphs"]
                ]
                return _Executable(
                    {
                        "documentId": documentId,
                        "revisionId": doc["revisionId"],
                        "body": {"content": content},
                        "inlineObjects": {},
                    }
                )

        return _Res()


class _Executable:
    def __init__(self, payload: Any):
        self._payload = payload

    def execute(self) -> Any:
        return self._payload


class _ContentSlidesService:
    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}

    def add(self, pres_id: str, revision: str = "r1") -> None:
        self.store[pres_id] = {"revisionId": revision}

    def presentations(self):  # noqa: ANN202
        service = self

        class _Res:
            def get(self, *, presentationId: str, fields: str | None = None):  # noqa: ANN202
                pres = service.store[presentationId]
                return _Executable(
                    {
                        "presentationId": presentationId,
                        "revisionId": pres["revisionId"],
                        "slides": [],
                    }
                )

        return _Res()


def _content_qa(paragraphs: list[str], **expectation_kwargs: Any):
    """Run terminal QA with one docs content expectation, no visuals."""
    docs = _ContentDocsService()
    docs.add("doc-1", paragraphs)
    slides = _ContentSlidesService()
    slides.add("slides-1")
    expectations = TerminalQAExpectations(
        idempotency_key=KEY,
        docs_content=(
            ContentExpectation(
                artifact_type="docs",
                token="<redacted>",
                expected_text="Fractions Intro",
                **expectation_kwargs,
            ),
        ),
    )
    return run_terminal_qa(
        expectations=expectations,
        slides_service=slides,
        docs_service=docs,
        slides_file_id="slides-1",
        worksheet_file_id="doc-1",
        receipts_dir=None,
        qa_evidence_dir=None,
    )


def test_duplicated_content_without_max_occurrences_is_not_a_failure():
    """Governed behavior: duplication is opt-in; without max_occurrences
    repeated content is not a failure."""
    report = _content_qa(["Fractions Intro and Fractions Intro"])
    assert "qa-content-duplicated" not in _codes(report)
    assert report.worksheet.state == QA_STATE_VERIFIED, _codes(report)


def test_duplicated_content_beyond_max_occurrences_fails():
    report = _content_qa(
        ["Fractions Intro and Fractions Intro"], max_occurrences=1
    )
    assert "qa-content-duplicated" in _codes(report)
    assert report.worksheet.state != QA_STATE_VERIFIED


def test_duplicated_content_within_max_occurrences_passes():
    report = _content_qa(
        ["Fractions Intro and Fractions Intro"], max_occurrences=2
    )
    assert "qa-content-duplicated" not in _codes(report)
    assert report.worksheet.state == QA_STATE_VERIFIED, _codes(report)
