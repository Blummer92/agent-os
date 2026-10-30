"""Independent offline #3257 + #3258 integration tests.

Run on a disposable joint checkout. Uses only fake Google services and a
separate pytest tmp_path receipt store; never contacts Google or GitHub.
"""
from __future__ import annotations

import pytest

from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_VERIFIED,
    QA_STATE_ARTIFACT_STALE,
)
from instructional_materials_coach.connected_visual_placement import (
    _revision_chain_is_current,
)
from instructional_materials_coach.placement_receipts import (
    append_placement_record,
    load_placement_records,
    reconcile_placement_batch,
)
from test_3258_terminal_content_qa import (
    FakeDocsService,
    _expectations,
    _run,
    _store_receipt,
    _visual,
    KEY,
)

ROLES = ('worked-example', 'comparison', 'diagram', 'reference')


def _reconcile_fixture_proof(receipts_dir, records, *, artifact_type, artifact_id,
                             initial_revision_id, final_revision_id):
    """Reconcile a batch proof over hand-built fixture receipts.

    The governed placement path always persists a reconciled batch proof,
    so fixtures modeling legitimate placements must include one: terminal
    QA's strict rule fails a multi-receipt batch without its proof closed
    (``qa-batch-proof-missing``), never falls back to per-receipt
    admission. Continuity is derived from the receipts' own recorded
    pre/post revisions; ``reconcile_placement_batch`` validates the chain
    links.
    """
    members = [
        {
            "role_id": record["role_id"],
            "slot_id": str(record["slot_id"]),
            "batch_artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "asset_id": record["asset_id"],
            "drive_file_id": record["drive_file_id"],
            "content_identity": dict(record["content_identity"]),
            "inserted_element_id": record["inserted_element_id"],
            "post_insertion_revision_id": record["post_insertion_revision_id"],
            "member_source": "placed",
        }
        for record in records
    ]
    continuity = [
        {
            "role_id": record["role_id"],
            "slot_id": str(record["slot_id"]),
            "inserted_element_id": record["inserted_element_id"],
            "pre_revision_id": record["artifact_revision_id"],
            "post_revision_id": record["post_insertion_revision_id"],
        }
        for record in records
    ]
    return reconcile_placement_batch(
        receipts_dir=receipts_dir,
        idempotency_key=KEY,
        batch_artifact_type=artifact_type,
        artifact_id=artifact_id,
        ordered_members=members,
        insertion_continuity=continuity,
        initial_revision_id=initial_revision_id,
        final_revision_id=final_revision_id,
    )


def _four_placements(tmp_path, reconcile_proof=True):
    receipts_dir = tmp_path / 'receipts'
    docs = FakeDocsService()
    docs.add('doc-1', ['Worksheet'], [f'img-{i}' for i in range(1, 5)], revision='r5')
    # The helper creates the first receipt in the shared build ledger.
    first = _store_receipt(
        receipts_dir, role_id=ROLES[0], revision='r2', inserted='img-1'
    )
    # Subsequent receipts record the actual before/after revisions.
    # All four roles deliberately share the same approved asset to exercise
    # the role-scoped rather than file-scoped identity contract.
    for i, role in enumerate(ROLES[1:], 2):
        record = dict(first)
        record.update(
            role_id=role,
            marker='{{visual:' + role + '}}',
            inserted_element_id=f'img-{i}',
            artifact_revision_id=f'r{i}',
            post_insertion_revision_id=f'r{i+1}',
        )
        record.pop('recorded_at', None)
        append_placement_record(receipts_dir, KEY, record)
    expected = _expectations(visuals=tuple(_visual(role) for role in ROLES))
    records = load_placement_records(receipts_dir, KEY)
    assert len(records) == len(ROLES)
    if reconcile_proof:
        _reconcile_fixture_proof(
            receipts_dir, records, artifact_type='docs', artifact_id='doc-1',
            initial_revision_id='r0', final_revision_id='r5',
        )
    return docs, receipts_dir, expected, records


def test_four_legitimate_placements_pass_terminal_qa(tmp_path):
    """Cross-component acceptance: valid r2->r3->r4->r5 is not external drift.

    The revision chain alone is no longer sufficient for a multi-receipt
    batch: the fixture reconciles the batch proof the governed placement
    path always persists, and terminal QA admits the members the proof
    revalidates (strict fail-closed without it).
    """
    docs, receipts_dir, expected, records = _four_placements(tmp_path)
    assert _revision_chain_is_current(records[0], records, 'r5')
    result = _run(docs=docs, receipts_dir=receipts_dir, expectations=expected)
    assert result.worksheet.state == QA_STATE_VERIFIED, (
        result.worksheet.state,
        [(finding.code, finding.message) for finding in result.worksheet.findings],
    )
    assert result.state == QA_STATE_VERIFIED


def test_four_placements_reject_external_revision_drift(tmp_path):
    docs, receipts_dir, expected, records = _four_placements(tmp_path)
    docs.docs['doc-1']['revisionId'] = 'teacher-edit-r6'
    assert not _revision_chain_is_current(records[0], records, 'teacher-edit-r6')
    result = _run(docs=docs, receipts_dir=receipts_dir, expectations=expected)
    assert result.worksheet.state == QA_STATE_ARTIFACT_STALE
    assert result.state != QA_STATE_VERIFIED


def test_four_placements_reject_deleted_middle_image(tmp_path):
    docs, receipts_dir, expected, _ = _four_placements(tmp_path)
    docs.docs['doc-1']['inline_objects'].remove('img-2')
    result = _run(docs=docs, receipts_dir=receipts_dir, expectations=expected)
    assert result.state != QA_STATE_VERIFIED
    assert any(f.code == 'qa-visual-element-mismatch' for f in result.worksheet.findings)


def test_four_placements_cache_recovery_rejects_receipt_mutation(tmp_path):
    """An independently re-verified success must be tied to receipt bytes."""
    docs, receipts_dir, expected, _ = _four_placements(tmp_path)
    qa_dir = tmp_path / 'terminal-qa'
    first = _run(docs=docs, receipts_dir=receipts_dir, expectations=expected, qa_evidence_dir=qa_dir)
    # This must exercise the positive cached-success path. No skipping
    # permitted if a valid multi-image placement is wrongly rejected.
    assert first.state == QA_STATE_VERIFIED
    assert not first.worksheet.recovered
    second = _run(docs=docs, receipts_dir=receipts_dir, expectations=expected, qa_evidence_dir=qa_dir)
    assert second.worksheet.recovered
    from instructional_materials_coach.placement_receipts import placement_record_path
    path = placement_record_path(receipts_dir, KEY)
    path.write_bytes(path.read_bytes() + b' ')
    changed = _run(docs=docs, receipts_dir=receipts_dir, expectations=expected, qa_evidence_dir=qa_dir)
    assert not changed.worksheet.recovered



def _four_slides(tmp_path, reconcile_proof=True):
    """Four successive Slides image placements on one slide, r1 -> r5."""
    from test_3258_terminal_content_qa import FakeSlidesService
    slides = FakeSlidesService()
    slides.add('slides-1', [{
        'objectId': 'slide-1',
        'elements': [{'objectId': f'img-{i}', 'image': True} for i in range(1, 5)],
    }], revision='r5')
    root = tmp_path / 'receipts'
    first = _store_receipt(
        root, role_id=ROLES[0], artifact_type='slides', artifact_id='slides-1',
        revision='r2', inserted='img-1', container_id='slide-1',
    )
    for i, role in enumerate(ROLES[1:], 2):
        record = dict(first)
        record.update(
            role_id=role, marker='{{visual:' + role + '}}',
            inserted_element_id=f'img-{i}',
            artifact_revision_id=f'r{i}',
            post_insertion_revision_id=f'r{i+1}',
        )
        record.pop('recorded_at', None)
        append_placement_record(root, KEY, record)
    if reconcile_proof:
        _reconcile_fixture_proof(
            root, load_placement_records(root, KEY),
            artifact_type='slides', artifact_id='slides-1',
            initial_revision_id='r0', final_revision_id='r5',
        )
    return slides, root, _expectations(visuals=tuple(_visual(role) for role in ROLES))


def test_four_legitimate_slides_placements_pass_terminal_qa(tmp_path):
    slides, root, expected = _four_slides(tmp_path)
    result = _run(slides=slides, receipts_dir=root, expectations=expected)
    assert result.slides.state == QA_STATE_VERIFIED, (
        result.slides.state,
        [(f.code, f.message) for f in result.slides.findings],
    )
    assert result.state == QA_STATE_VERIFIED


def test_four_slides_placements_reject_deleted_middle_image(tmp_path):
    slides, root, expected = _four_slides(tmp_path)
    slide = slides.presentations_store['slides-1']['slides'][0]
    slide['elements'] = [e for e in slide['elements'] if e['objectId'] != 'img-2']
    result = _run(slides=slides, receipts_dir=root, expectations=expected)
    assert result.state != QA_STATE_VERIFIED
    assert any(f.code == 'qa-visual-element-mismatch' for f in result.slides.findings)


def test_four_placements_reject_broken_revision_chain(tmp_path):
    """A missing recorded edge r3->r4 cannot be mistaken for a safe edit.

    No batch proof is reconciled here on purpose: the mutated ledger must
    fail closed through the strict missing-proof rule (a multi-receipt
    batch without its reconciled proof is never admitted), not through
    per-receipt chain admission.
    """
    import json
    from instructional_materials_coach.placement_receipts import placement_record_path
    docs, root, expected, _ = _four_placements(tmp_path, reconcile_proof=False)
    path = placement_record_path(root, KEY)
    payload = json.loads(path.read_text(encoding='utf-8'))
    payload['records'][2]['artifact_revision_id'] = 'unaccounted-r3'
    path.write_text(json.dumps(payload), encoding='utf-8')
    result = _run(docs=docs, receipts_dir=root, expectations=expected)
    assert result.worksheet.state == QA_STATE_ARTIFACT_STALE
    assert result.state != QA_STATE_VERIFIED


def test_four_placements_reject_missing_post_revision(tmp_path):
    """Missing revision evidence cannot fall back to marker/image-ID only.

    No batch proof is reconciled here on purpose: the malformed ledger
    must fail closed through the strict receipt-ledger validation, not
    through proof admission.
    """
    import json
    from instructional_materials_coach.placement_receipts import placement_record_path
    docs, root, expected, _ = _four_placements(tmp_path, reconcile_proof=False)
    path = placement_record_path(root, KEY)
    payload = json.loads(path.read_text(encoding='utf-8'))
    payload['records'][1].pop('post_insertion_revision_id')
    path.write_text(json.dumps(payload), encoding='utf-8')
    result = _run(docs=docs, receipts_dir=root, expectations=expected)
    assert result.worksheet.state == "evidence-incomplete"
    assert result.state != QA_STATE_VERIFIED


# The #3257 interruption journal is separate from #3258 receipt cache bytes.
# Unresolved or abandoned write intent must block terminal QA even if the
# persisted artifact revision and placement-receipt digest are unchanged.

def _begin_optional_unreceipted_attempt(receipts_dir):
    from instructional_materials_coach.placement_receipts import begin_placement_attempt
    begin_placement_attempt(receipts_dir, KEY, {
        "artifact_type": "docs", "artifact_id": "doc-1",
        "role_id": "optional-extra", "slot_id": "0",
        "asset_id": "asset-optional", "drive_file_id": "file-optional",
        "source_plan_id": "plan-1", "content_identity": {"sha256": "abc123"},
        "artifact_revision_id": "r1", "marker": "{{visual:optional-extra}}",
        "container_id": "body",
    })

def test_terminal_qa_cannot_cache_success_with_pending_attempt(tmp_path):
    from test_3258_terminal_content_qa import _cache_receipt_fixture, _cache_receipt_rerun
    fixture = _cache_receipt_fixture(tmp_path)
    assert _cache_receipt_rerun(fixture).worksheet.recovered
    _begin_optional_unreceipted_attempt(fixture[1])
    report = _cache_receipt_rerun(fixture)
    assert report.state != QA_STATE_VERIFIED
    assert not report.worksheet.recovered
    assert any(f.code == "qa-placement-attempt-unresolved" for f in report.worksheet.findings)

def test_terminal_qa_optional_only_attempt_blocks_fresh_success(tmp_path):
    from test_3258_terminal_content_qa import FakeDocsService, _expectations, _run, _visual
    docs = FakeDocsService()
    docs.add("doc-1", ["Worksheet"], [], revision="r1")
    receipts_dir = tmp_path / "receipts"
    expected = _expectations(visuals=(_visual("optional-extra", required=False),))
    before = _run(docs=docs, receipts_dir=receipts_dir, expectations=expected)
    assert before.state == QA_STATE_VERIFIED
    _begin_optional_unreceipted_attempt(receipts_dir)
    after = _run(docs=docs, receipts_dir=receipts_dir, expectations=expected)
    assert after.state != QA_STATE_VERIFIED
    assert any(f.code == "qa-placement-attempt-unresolved" for f in after.worksheet.findings)

def test_terminal_qa_checks_journal_even_when_no_visual_expected(tmp_path):
    from test_3258_terminal_content_qa import FakeDocsService, _expectations, _run
    docs = FakeDocsService()
    docs.add("doc-1", ["Worksheet"], [], revision="r1")
    receipts_dir = tmp_path / "receipts"
    expected = _expectations(visuals=())
    first = _run(docs=docs, receipts_dir=receipts_dir, expectations=expected)
    assert first.state == QA_STATE_VERIFIED
    _begin_optional_unreceipted_attempt(receipts_dir)
    second = _run(docs=docs, receipts_dir=receipts_dir, expectations=expected)
    assert second.state != QA_STATE_VERIFIED
    assert any(f.code == "qa-placement-attempt-unresolved" for f in second.worksheet.findings)



def test_terminal_qa_rejects_invalid_unselected_receipt(tmp_path):
    """A valid expected worksheet cannot hide a malformed orphan in its ledger."""
    import json
    from instructional_materials_coach.placement_receipts import placement_record_path
    docs, receipts_dir, expected, _ = _four_placements(tmp_path)
    path = placement_record_path(receipts_dir, KEY)
    payload = json.loads(path.read_text(encoding="utf-8"))
    orphan = dict(payload["records"][0])
    orphan.update(role_id="abandoned-optional", slot_id="99", source_plan_id="")
    payload["records"].append(orphan)
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = _run(docs=docs, receipts_dir=receipts_dir, expectations=expected)
    assert result.state != QA_STATE_VERIFIED
    assert any(f.code == "qa-placement-evidence-unavailable" for f in result.worksheet.findings)


def test_terminal_qa_rejects_duplicate_unselected_receipts(tmp_path):
    """Duplicate unrelated receipts invalidate the complete build snapshot."""
    import json
    from instructional_materials_coach.placement_receipts import placement_record_path
    docs, receipts_dir, expected, _ = _four_placements(tmp_path)
    path = placement_record_path(receipts_dir, KEY)
    payload = json.loads(path.read_text(encoding="utf-8"))
    orphan = dict(payload["records"][0])
    orphan.update(role_id="abandoned-optional", slot_id="99", marker="{{visual:abandoned-optional}}")
    payload["records"].extend((orphan, dict(orphan)))
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = _run(docs=docs, receipts_dir=receipts_dir, expectations=expected)
    assert result.state != QA_STATE_VERIFIED
    assert any(f.code == "qa-placement-evidence-unavailable" for f in result.worksheet.findings)



# #3257/#3258 independent red/green ledger-integrity follow-up.
# Both paths must reject unselected invalid evidence, and a previously
# verified terminal cache must not mask the changed receipt snapshot.

@pytest.mark.parametrize("case", (
    "two-roles-one-image",
    "unselected-unsupported-artifact-type",
    "unselected-malformed-required-flag",
))
@pytest.mark.parametrize("cached", (False, True), ids=("fresh", "cached"))
def test_terminal_qa_rejects_invalid_whole_ledger_domains_and_physical_claims(tmp_path, case, cached):
    """Prove terminal QA does not count one image twice or ignore invalid orphans."""
    import json
    from instructional_materials_coach.placement_receipts import placement_record_path

    docs, receipts_dir, expected, _ = _four_placements(tmp_path)
    qa_dir = tmp_path / "qa" if cached else None

    if cached:
        initial = _run(docs=docs, receipts_dir=receipts_dir,
                       expectations=expected, qa_evidence_dir=qa_dir)
        assert initial.state == QA_STATE_VERIFIED
        assert not initial.worksheet.recovered
        replay = _run(docs=docs, receipts_dir=receipts_dir,
                      expectations=expected, qa_evidence_dir=qa_dir)
        assert replay.state == QA_STATE_VERIFIED
        assert replay.worksheet.recovered

    path = placement_record_path(receipts_dir, KEY)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if case == "two-roles-one-image":
        # Both selected roles point to one existing physical inline image.
        # Their role IDs differ, so the older role/slot-only checker allowed it.
        payload["records"][1]["inserted_element_id"] = payload["records"][0]["inserted_element_id"]
    else:
        # A formerly selected role may be absent from current expectations;
        # it must still be validated as part of the complete build ledger.
        orphan = dict(payload["records"][0])
        orphan.update(role_id="removed-role", slot_id="99",
                      marker="{{visual:removed-role}}", inserted_element_id="orphan-image-99")
        if case == "unselected-unsupported-artifact-type":
            orphan["artifact_type"] = "bogus"
        elif case == "unselected-malformed-required-flag":
            orphan["required"] = "false"  # string, not a governed boolean
        else:
            raise AssertionError(case)
        payload["records"].append(orphan)
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = _run(docs=docs, receipts_dir=receipts_dir,
                  expectations=expected, qa_evidence_dir=qa_dir)
    assert result.state != QA_STATE_VERIFIED
    assert result.worksheet.state == "evidence-incomplete"
    assert any(f.code == "qa-placement-evidence-unavailable" for f in result.worksheet.findings)
    assert not result.worksheet.recovered
