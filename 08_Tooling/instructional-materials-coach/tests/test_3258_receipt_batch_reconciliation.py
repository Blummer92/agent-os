"""#3258: reconciled batch placement proofs (R1 consumer repair).

Sequential genuine insertions each advance the artifact revision, so the
original per-insertion receipts legitimately disagree with the final
revision. The repair: ``execute_artifact_visual_placements`` observes the
artifact before/after every insertion, verifies per-insertion mutation
continuity, and persists an atomic reconciled batch proof bound to the
ordered complete receipt set, exact asset/content/element identities,
artifact/build identity, the observed final revision, and verified
continuity. Terminal QA consumes the proof for members it revalidates;
a missing proof (when required: strict fail-closed, never a permissive
per-receipt fallback), conflicting, or tampered proofs fail closed
(manual review), never verify. Original per-insertion receipts are never
rewritten.

The proof-side artifact field is ``batch_artifact_type`` -- deliberately
distinct from the receipt envelope's ``artifact_type`` (and from #3643's
``VisualExpectation.artifact_type`` obligation-scope concept).

All external interaction uses injected fakes; no live Docs/Slides/Drive
mutation occurs in this suite.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_ARTIFACT_CONFLICT,
    QA_STATE_ARTIFACT_STALE,
    QA_STATE_VERIFIED,
    TerminalQAExpectations,
    run_terminal_qa,
)
from instructional_materials_coach.connected_visual_placement import (
    PlacementExecutionError,
    execute_artifact_visual_placements,
)
from instructional_materials_coach.placement_receipts import (
    append_placement_record,
    batch_proof_fingerprint,
    load_batch_proofs,
    load_placement_records,
    reconcile_placement_batch,
)
from instructional_materials_coach.placement_transport import PlacementTransportError


# Reuse the #3257 suite's service fakes (injected, offline).
_FAKE_MODULE = Path(__file__).with_name("test_3257_connected_visual_placement.py")
_spec = importlib.util.spec_from_file_location("_r1_fakes_3257", _FAKE_MODULE)
assert _spec is not None and _spec.loader is not None
_fakes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fakes)

KEY = "k" * 64


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


def _slides_env(n: int):
    bindings = tuple(
        _fakes._binding(f"figure-{i}", asset_id=f"asset-{i}", drive_file_id=f"file-{i}")
        for i in range(n)
    )
    slides = _fakes.FakeSlidesService()
    slides.add_presentation(
        "slides-1",
        [
            {
                "objectId": "slide-1",
                "elements": [
                    {"objectId": f"marker-{i}", "text": f"{{{{visual:figure-{i}}}}}"}
                    for i in range(n)
                ],
            }
        ],
    )
    drive = _fakes.FakeDriveService(
        {f"file-{i}": _fakes._drive_metadata(f"file-{i}") for i in range(n)}
    )
    transport = _fakes.FakePlacementTransport(slides=slides)
    return bindings, slides, drive, transport


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


def _empty_slides():
    slides = _fakes.FakeSlidesService()
    slides.add_presentation("slides-1", [], revision="r1")
    return slides


def _terminal_qa(bindings, docs, receipts_dir, qa_dir=None, key=KEY):
    expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key=key, visual_placements=bindings
    )
    return run_terminal_qa(
        expectations=expectations,
        slides_service=_empty_slides(),
        docs_service=docs,
        slides_file_id="slides-1",
        worksheet_file_id="doc-1",
        receipts_dir=str(receipts_dir),
        qa_evidence_dir=str(qa_dir) if qa_dir is not None else None,
    )


def _codes(report) -> list[str]:
    return [f.code for f in report.worksheet.findings]


def _rewrite_store(receipts_dir, key, mutator):
    """Apply a hostile-but-plausible mutation to the persisted store file."""
    path = Path(receipts_dir) / f"{key}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutator(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Positive acceptance: 1 / 2 / 4 genuine sequential images verify
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 2, 4])
def test_sequential_genuine_images_verify(tmp_path, n):
    bindings, docs, drive, transport = _docs_env(n)
    receipts_dir = tmp_path / "receipts"
    outcomes = _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert [o.status for o in outcomes] == ["placed"] * n

    records = load_placement_records(receipts_dir, KEY)
    # Original per-insertion receipts are preserved: genuine observed
    # revisions, never re-stamped with the final revision.
    assert [r["post_insertion_revision_id"] for r in records] == [
        "r1" + "-p" * (i + 1) for i in range(n)
    ]
    proofs = load_batch_proofs(receipts_dir, KEY)
    assert len(proofs) == 1
    proof = proofs[0]
    assert proof["final_revision_id"] == "r1" + "-p" * n
    assert [m["post_insertion_revision_id"] for m in proof["ordered_members"]] == [
        r["post_insertion_revision_id"] for r in records
    ]
    assert [m["member_source"] for m in proof["ordered_members"]] == ["placed"] * n
    assert len(proof["insertion_continuity"]) == n

    report = _terminal_qa(bindings, docs, receipts_dir)
    assert report.worksheet.state == QA_STATE_VERIFIED, _codes(report)
    assert "qa-artifact-stale" not in _codes(report)
    assert report.state == QA_STATE_VERIFIED


def test_slides_two_genuine_images_verify(tmp_path):
    bindings, slides, drive, transport = _slides_env(2)
    receipts_dir = tmp_path / "receipts"
    outcomes = execute_artifact_visual_placements(
        bindings=bindings,
        artifact_type="slides",
        artifact_id="slides-1",
        drive_service=drive,
        artifact_service=slides,
        transport=transport,
        receipts_dir=str(receipts_dir),
        idempotency_key=KEY,
    )
    assert [o.status for o in outcomes] == ["placed", "placed"]
    proofs = load_batch_proofs(receipts_dir, KEY)
    assert len(proofs) == 1 and proofs[0]["final_revision_id"] == "r1-p-p"

    expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key=KEY, visual_placements=bindings
    )
    docs = _fakes.FakeDocsService()
    docs.add_document("doc-1", [], revision="r1")
    report = run_terminal_qa(
        expectations=expectations,
        slides_service=slides,
        docs_service=docs,
        slides_file_id="slides-1",
        worksheet_file_id="doc-1",
        receipts_dir=str(receipts_dir),
    )
    assert report.slides.state == QA_STATE_VERIFIED, [f.code for f in report.slides.findings]
    assert report.state == QA_STATE_VERIFIED


def test_pure_recovery_run_reconciles(tmp_path):
    bindings, docs, drive, transport = _docs_env(2)
    receipts_dir = tmp_path / "receipts"
    _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert len(load_batch_proofs(receipts_dir, KEY)) == 1
    # Second run: everything recovered, nothing inserted. The batch is
    # re-reconciled against the unchanged artifact; the new proof
    # supersedes the previous one for this artifact.
    outcomes = _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert [o.status for o in outcomes] == ["recovered", "recovered"]
    proofs = load_batch_proofs(receipts_dir, KEY)
    assert len(proofs) == 1
    assert [m["member_source"] for m in proofs[0]["ordered_members"]] == [
        "recovered",
        "recovered",
    ]
    assert proofs[0]["final_revision_id"] == "r1-p-p"
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert report.worksheet.state == QA_STATE_VERIFIED


# ---------------------------------------------------------------------------
# Negative: intervening / post-reconciliation / same-ID mutations
# ---------------------------------------------------------------------------


def test_injected_intervening_edit_rejected(tmp_path, monkeypatch):
    bindings, docs, drive, transport = _docs_env(2)
    receipts_dir = tmp_path / "receipts"
    import instructional_materials_coach.connected_visual_placement as cvp

    real_place_one = cvp._place_one_binding
    calls: list[str] = []

    def _evil_place_one(*, binding, **kwargs):
        if calls:
            # The first insertion fully completed (continuity verified,
            # receipt stored). An external edit slips in before the second
            # insertion starts: real content mutation, which always
            # advances the revision.
            doc = docs.documents_store["doc-1"]
            doc["paragraphs"][0] += " [external edit]"
            doc["revisionId"] += "-external"
        calls.append(binding.role_id)
        return real_place_one(binding=binding, **kwargs)

    monkeypatch.setattr(cvp, "_place_one_binding", _evil_place_one)
    with pytest.raises(PlacementExecutionError, match="placement-batch-unreconciled"):
        _place_docs(bindings, docs, drive, transport, receipts_dir)
    # Fail closed: no batch proof is written for the broken chain.
    assert load_batch_proofs(receipts_dir, KEY) == ()


def test_edit_after_reconciliation_rejected(tmp_path):
    bindings, docs, drive, transport = _docs_env(2)
    receipts_dir = tmp_path / "receipts"
    _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert _terminal_qa(bindings, docs, receipts_dir).worksheet.state == QA_STATE_VERIFIED
    # External edit after reconciliation: element ids intact, bytes moved on.
    docs.documents_store["doc-1"]["revisionId"] += "-external"
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert report.worksheet.state == QA_STATE_ARTIFACT_STALE
    assert "qa-artifact-stale" in _codes(report)


def test_deleted_member_element_rejected(tmp_path):
    # The proof verifies, but a member's element is gone from the
    # artifact: the proof goes stale with the element-mismatch finding,
    # never verification.
    bindings, docs, drive, transport = _docs_env(2)
    receipts_dir = tmp_path / "receipts"
    _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert _terminal_qa(bindings, docs, receipts_dir).worksheet.state == QA_STATE_VERIFIED
    inline = docs.documents_store["doc-1"]["inline_objects"]
    records = load_placement_records(receipts_dir, KEY)
    inline.remove(records[0]["inserted_element_id"])
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert report.worksheet.state != QA_STATE_VERIFIED
    assert "qa-visual-element-mismatch" in _codes(report)


def test_same_id_byte_replacement_rejected(tmp_path):
    bindings, docs, drive, _ = _docs_env(2)
    docs.documents_store["doc-1"]["inline_objects"].append("pre-existing-id")
    receipts_dir = tmp_path / "receipts"

    class _ReusedIdTransport(_fakes.FakePlacementTransport):
        def insert_placement(self, *, request):
            super().insert_placement(request=request)
            # The runtime claims an element id that predates this insertion:
            # it cannot prove these bytes are the new insertion.
            return {"state": "placed", "inserted_element_id": "pre-existing-id"}

    with pytest.raises(PlacementExecutionError, match="placement-element-id-reused"):
        _place_docs(bindings, docs, drive, _ReusedIdTransport(docs=docs), receipts_dir)
    assert load_batch_proofs(receipts_dir, KEY) == ()


def test_drift_between_runs_rejected(tmp_path):
    bindings, docs, drive, transport = _docs_env(1)
    receipts_dir = tmp_path / "receipts"
    _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert len(load_batch_proofs(receipts_dir, KEY)) == 1
    # External edit between two runs: the recovered binding's revision
    # chain no longer reaches the live revision, so the carrier's recovery
    # path fails the run closed before batch reconciliation is reached.
    docs.documents_store["doc-1"]["revisionId"] += "-external"
    with pytest.raises(PlacementExecutionError, match="placement-recovery-stale"):
        _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert len(load_batch_proofs(receipts_dir, KEY)) == 1


def test_batch_reconcile_refuses_drift_across_proof_anchor(tmp_path):
    # The batch-level drift anchor: a prior proof exists, the artifact
    # moved, and the second run places only a NEW binding (no recovery
    # path runs). Reconciliation must refuse to bridge the unexplained
    # drift between the proof's final revision and the run's initial
    # observation.
    bindings, docs, drive, transport = _docs_env(1)
    receipts_dir = tmp_path / "receipts"
    _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert len(load_batch_proofs(receipts_dir, KEY)) == 1
    docs.documents_store["doc-1"]["revisionId"] += "-external"
    docs.documents_store["doc-1"]["paragraphs"].append("{{visual:figure-9}}")
    new_bindings = (
        _fakes._binding("figure-9", asset_id="asset-9", drive_file_id="file-9"),
    )
    drive2 = _fakes.FakeDriveService({"file-9": _fakes._drive_metadata("file-9")})
    with pytest.raises(PlacementExecutionError, match="placement-batch-unreconciled"):
        execute_artifact_visual_placements(
            bindings=new_bindings,
            artifact_type="docs",
            artifact_id="doc-1",
            drive_service=drive2,
            artifact_service=docs,
            transport=transport,
            receipts_dir=str(receipts_dir),
            idempotency_key=KEY,
        )
    assert len(load_batch_proofs(receipts_dir, KEY)) == 1


# ---------------------------------------------------------------------------
# Negative: swapped identities, missing member, tampered/conflicting proofs
# ---------------------------------------------------------------------------


def test_swapped_identities_rejected(tmp_path):
    bindings, docs, drive, transport = _docs_env(2)
    receipts_dir = tmp_path / "receipts"
    _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert _terminal_qa(bindings, docs, receipts_dir).worksheet.state == QA_STATE_VERIFIED

    def _swap(payload):
        records = payload["records"]
        records[0]["asset_id"], records[1]["asset_id"] = (
            records[1]["asset_id"],
            records[0]["asset_id"],
        )

    _rewrite_store(receipts_dir, KEY, _swap)
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert not report.worksheet.recovered
    assert report.worksheet.state != QA_STATE_VERIFIED
    assert "qa-batch-proof-invalid" in _codes(report)


def test_missing_member_rejected(tmp_path):
    bindings, docs, drive, transport = _docs_env(2)
    receipts_dir = tmp_path / "receipts"
    _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert _terminal_qa(bindings, docs, receipts_dir).worksheet.state == QA_STATE_VERIFIED

    def _drop(payload):
        payload["records"] = payload["records"][:1]

    _rewrite_store(receipts_dir, KEY, _drop)
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert not report.worksheet.recovered
    assert report.worksheet.state != QA_STATE_VERIFIED
    assert "qa-batch-proof-invalid" in _codes(report)


def test_conflicting_proofs_rejected(tmp_path):
    bindings, docs, drive, transport = _docs_env(2)
    receipts_dir = tmp_path / "receipts"
    _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert _terminal_qa(bindings, docs, receipts_dir).worksheet.state == QA_STATE_VERIFIED
    # A second proof claiming the same artifact (only writable by foreign
    # tampering -- reconciliation supersedes) is conflicting evidence.
    existing = load_batch_proofs(receipts_dir, KEY)[0]

    def _duplicate_proof(payload):
        payload["batch_proofs"].append(json.loads(json.dumps(existing)))

    _rewrite_store(receipts_dir, KEY, _duplicate_proof)
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert report.worksheet.state == QA_STATE_ARTIFACT_CONFLICT
    assert "qa-batch-proof-conflict" in _codes(report)


def test_no_proof_fails_closed_strict(tmp_path):
    # Strict fail-closed (owner decision): a multi-receipt batch whose
    # reconciled proof is missing does NOT fall back to per-receipt
    # semantics -- the batch fails closed for manual review, never
    # verifies. (Supersedes the pre-repair "missing proofs keep
    # per-receipt semantics" behavior.)
    bindings, docs, drive, transport = _docs_env(2)
    receipts_dir = tmp_path / "receipts"
    _place_docs(bindings, docs, drive, transport, receipts_dir)

    def _strip_proofs(payload):
        payload.pop("batch_proofs", None)

    _rewrite_store(receipts_dir, KEY, _strip_proofs)
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert report.worksheet.state == QA_STATE_ARTIFACT_STALE
    assert "qa-batch-proof-missing" in _codes(report)
    # The per-receipt stale fallback must not double-report or admit the
    # batch: the missing-proof finding is the single fail-closed verdict.
    assert "qa-artifact-stale" not in _codes(report)


# ---------------------------------------------------------------------------
# Retry / idempotency and recovery-cache binding
# ---------------------------------------------------------------------------


def test_partial_retry_does_not_duplicate_images(tmp_path):
    bindings, docs, drive, _ = _docs_env(2)
    receipts_dir = tmp_path / "receipts"
    # One transport instance across both attempts, so inserted element ids
    # stay unique (as a real runtime's would); the first attempt fails on
    # the second binding. The fake raises PlacementNoMutation (attested
    # pre-mutation failure), so the attempt fence is proven clear and the
    # retry may proceed without reinserting.
    transport = _fakes.FakePlacementTransport(docs=docs, fail_for_roles={"figure-1"})
    with pytest.raises(PlacementExecutionError):
        _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert len(docs.documents_store["doc-1"]["inline_objects"]) == 1

    transport._fail_for_roles = set()
    outcomes = _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert [o.status for o in outcomes] == ["recovered", "placed"]
    # No duplicate image was inserted on retry.
    assert len(docs.documents_store["doc-1"]["inline_objects"]) == 2
    proofs = load_batch_proofs(receipts_dir, KEY)
    assert len(proofs) == 1
    assert [m["member_source"] for m in proofs[0]["ordered_members"]] == [
        "recovered",
        "placed",
    ]
    report = _terminal_qa(bindings, docs, receipts_dir)
    assert report.worksheet.state == QA_STATE_VERIFIED


def test_stale_qa_cache_after_receipt_membership_change_rejected(tmp_path):
    bindings, docs, drive, transport = _docs_env(2)
    receipts_dir = tmp_path / "receipts"
    qa_dir = tmp_path / "qa"
    _place_docs(bindings, docs, drive, transport, receipts_dir)
    first = _terminal_qa(bindings, docs, receipts_dir, qa_dir)
    assert first.worksheet.state == QA_STATE_VERIFIED
    assert not first.worksheet.recovered
    # Unchanged artifact/expectations still recover while identity holds.
    second = _terminal_qa(bindings, docs, receipts_dir, qa_dir)
    assert second.worksheet.recovered

    # Membership change: a new verified receipt lands in the store.
    extra = _fakes._binding("figure-2", asset_id="asset-2", drive_file_id="file-2")
    append_placement_record(
        receipts_dir,
        KEY,
        {
            "asset_id": "asset-2",
            "drive_file_id": "file-2",
            "role_id": "figure-2",
            "slot_id": "0",
            "artifact_type": "docs",
            "artifact_id": "doc-1",
            "artifact_revision_id": "r1",
            "marker": "{{visual:figure-2}}",
            "container_id": "body",
            "inserted_element_id": "img-extra",
            "state": "verified",
            "content_identity": dict(extra.content_identity),
            "source_plan_id": "cohesive-visual-plan-test",
            "required": True,
            "eligibility_evidence": None,
            "transport": "fake-test-transport",
            "post_insertion_revision_id": "r1-p-p",
            "placed_at": "2026-10-16T00:00:00+00:00",
        },
    )
    third = _terminal_qa(bindings, docs, receipts_dir, qa_dir)
    assert not third.worksheet.recovered, "cached verified QA was reused after receipt membership changed"


def test_stale_qa_cache_after_proof_change_rejected(tmp_path):
    bindings, docs, drive, transport = _docs_env(2)
    receipts_dir = tmp_path / "receipts"
    qa_dir = tmp_path / "qa"
    _place_docs(bindings, docs, drive, transport, receipts_dir)
    first = _terminal_qa(bindings, docs, receipts_dir, qa_dir)
    assert first.worksheet.state == QA_STATE_VERIFIED

    def _tamper_proof(payload):
        payload["batch_proofs"][0]["ordered_members"][0]["asset_id"] = "tampered-asset"

    _rewrite_store(receipts_dir, KEY, _tamper_proof)
    second = _terminal_qa(bindings, docs, receipts_dir, qa_dir)
    assert not second.worksheet.recovered, "cached verified QA was reused after the proof changed"
    assert second.worksheet.state != QA_STATE_VERIFIED
    assert "qa-batch-proof-invalid" in _codes(second)


# ---------------------------------------------------------------------------
# Store-level invariants
# ---------------------------------------------------------------------------


def test_proof_fingerprint_is_tamper_evident():
    proof = {
        "proof_contract": "visual-placement-batch-proof-v1",
        "idempotency_key": KEY,
        "batch_artifact_type": "docs",
        "artifact_id": "doc-1",
        "initial_revision_id": "r1",
        "final_revision_id": "r1-p",
        "ordered_members": [
            {
                "role_id": "figure-0",
                "slot_id": "0",
                "batch_artifact_type": "docs",
                "artifact_id": "doc-1",
                "asset_id": "asset-0",
                "drive_file_id": "file-0",
                "content_identity": {"sha256": "abc"},
                "inserted_element_id": "img-1",
                "post_insertion_revision_id": "r1-p",
                "member_source": "placed",
            }
        ],
        "insertion_continuity": [],
        "reconciled_at": "2026-10-16T00:00:00+00:00",
    }
    fingerprint = batch_proof_fingerprint(proof)
    assert isinstance(fingerprint, str) and len(fingerprint) == 64
    tampered = json.loads(json.dumps(proof))
    tampered["ordered_members"][0]["asset_id"] = "other-asset"
    assert batch_proof_fingerprint(tampered) != fingerprint
    # The timestamp alone is not semantic content.
    retimed = json.loads(json.dumps(proof))
    retimed["reconciled_at"] = "2027-01-01T00:00:00+00:00"
    assert batch_proof_fingerprint(retimed) == fingerprint


def test_append_record_preserves_batch_proofs(tmp_path):
    bindings, docs, drive, transport = _docs_env(1)
    receipts_dir = tmp_path / "receipts"
    _place_docs(bindings, docs, drive, transport, receipts_dir)
    assert len(load_batch_proofs(receipts_dir, KEY)) == 1
    append_placement_record(
        receipts_dir,
        KEY,
        {
            "asset_id": "asset-9",
            "drive_file_id": "file-9",
            "role_id": "figure-9",
            "slot_id": "0",
            "artifact_type": "docs",
            "artifact_id": "doc-1",
            "artifact_revision_id": "r1",
            "marker": "{{visual:figure-9}}",
            "container_id": "body",
            "inserted_element_id": "img-9",
            "state": "verified",
            "content_identity": {"sha256": "zzz"},
            "source_plan_id": "cohesive-visual-plan-test",
            "required": True,
            "eligibility_evidence": None,
            "transport": "fake-test-transport",
            "post_insertion_revision_id": "r1-p",
            "placed_at": "2026-10-16T00:00:00+00:00",
        },
    )
    assert len(load_batch_proofs(receipts_dir, KEY)) == 1
    assert len(load_placement_records(receipts_dir, KEY)) == 2


def _member(role, revision, source="placed"):
    return {
        "role_id": role,
        "slot_id": "0",
        "batch_artifact_type": "docs",
        "artifact_id": "doc-1",
        "asset_id": f"asset-{role}",
        "drive_file_id": f"file-{role}",
        "content_identity": {"sha256": role},
        "inserted_element_id": f"img-{role}",
        "post_insertion_revision_id": revision,
        "member_source": source,
    }


def test_reconcile_rejects_broken_chain():
    with pytest.raises(ValueError, match="insertion chain is broken"):
        reconcile_placement_batch(
            receipts_dir="/tmp/does-not-matter",
            idempotency_key=KEY,
            batch_artifact_type="docs",
            artifact_id="doc-1",
            ordered_members=[_member("a", "r2"), _member("b", "r3")],
            insertion_continuity=[
                {
                    "role_id": "a",
                    "slot_id": "0",
                    "inserted_element_id": "img-a",
                    "pre_revision_id": "r1",
                    "post_revision_id": "r2",
                },
                {
                    "role_id": "b",
                    "slot_id": "0",
                    "inserted_element_id": "img-b",
                    # Does not link to the previous post-revision: an edit
                    # slipped in between the two insertions.
                    "pre_revision_id": "r2-tampered",
                    "post_revision_id": "r3",
                },
            ],
            initial_revision_id="r1",
            final_revision_id="r3",
        )
