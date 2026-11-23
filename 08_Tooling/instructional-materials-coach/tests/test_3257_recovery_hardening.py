"""#3257 producer-side readback/recovery regressions (injected offline services)."""
from __future__ import annotations

import json

import pytest

from instructional_materials_coach.connected_visual_placement import (
    PlacementExecutionError,
    require_all_required_visuals_placed,
)
from instructional_materials_coach.placement_receipts import (
    load_placement_records,
    placement_record_path,
)
from instructional_materials_coach.visual_placement import marker_for_role
from test_3257_connected_visual_placement import (
    FakeDocsService,
    FakeDriveService,
    FakePlacementTransport,
    FakeSlidesService,
    _binding,
    _docs_harness,
    _drive_metadata,
    _execute,
)

KEY = 'k' * 64


def _docs_placed(tmp_path):
    docs, slides, drive, transport = _docs_harness(tmp_path)
    binding = _binding('worked-example')
    receipts_dir = tmp_path / 'receipts'
    (first,) = _execute([binding], artifact_type='docs', artifact_id='doc-1',
                        drive=drive, docs=docs, slides=slides,
                        transport=transport, receipts_dir=receipts_dir)
    assert first.status == 'placed'
    return docs, slides, drive, binding, receipts_dir


def _slides_placed(tmp_path):
    docs = FakeDocsService()
    slides = FakeSlidesService()
    slides.add_presentation('pres-1', [
        {'objectId': 'slide-1', 'elements': [
            {'objectId': 'shape-1', 'text': marker_for_role('worked-example')},
        ]},
        {'objectId': 'slide-2', 'elements': []},
    ])
    drive = FakeDriveService({'file-1': _drive_metadata('file-1')})
    binding = _binding('worked-example')
    receipts_dir = tmp_path / 'receipts'
    (first,) = _execute([binding], artifact_type='slides', artifact_id='pres-1',
                        drive=drive, docs=docs, slides=slides,
                        transport=FakePlacementTransport(docs=docs, slides=slides),
                        receipts_dir=receipts_dir)
    assert first.status == 'placed'
    return docs, slides, drive, binding, receipts_dir


def _rewrite_record(receipts_dir, field, value):
    path = placement_record_path(receipts_dir, KEY)
    data = json.loads(path.read_text(encoding='utf-8'))
    data['records'][0][field] = value
    path.write_text(json.dumps(data), encoding='utf-8')


def _retry_docs(fixture):
    docs, slides, drive, binding, receipts_dir = fixture
    transport = FakePlacementTransport(docs=docs, slides=slides)
    def run():
        return _execute([binding], artifact_type='docs', artifact_id='doc-1',
                        drive=drive, docs=docs, slides=slides,
                        transport=transport, receipts_dir=receipts_dir)
    return run, transport


def _retry_slides(fixture):
    docs, slides, drive, binding, receipts_dir = fixture
    transport = FakePlacementTransport(docs=docs, slides=slides)
    def run():
        return _execute([binding], artifact_type='slides', artifact_id='pres-1',
                        drive=drive, docs=docs, slides=slides,
                        transport=transport, receipts_dir=receipts_dir)
    return run, transport


def test_recovery_valid_docs_receipt_stays_idempotent(tmp_path):
    fixture = _docs_placed(tmp_path)
    run, transport = _retry_docs(fixture)
    (outcome,) = run()
    assert outcome.status == 'recovered'
    assert transport.calls == []
    assert len(load_placement_records(fixture[-1], KEY)) == 1


def test_recovery_valid_slides_receipt_stays_idempotent(tmp_path):
    fixture = _slides_placed(tmp_path)
    run, transport = _retry_slides(fixture)
    (outcome,) = run()
    assert outcome.status == 'recovered'
    assert transport.calls == []


def test_recovery_deleted_docs_image_fails_closed(tmp_path):
    fixture = _docs_placed(tmp_path)
    fixture[0].documents_store['doc-1']['inline_objects'].clear()
    run, transport = _retry_docs(fixture)
    with pytest.raises(PlacementExecutionError, match='placement-recovery-stale'):
        run()
    assert transport.calls == []


@pytest.mark.parametrize('field,value', [
    ('asset_id', 'forged-asset'),
    ('drive_file_id', 'other-file'),
    ('source_plan_id', 'other-plan'),
])
def test_recovery_conflicting_selection_receipt_fails_closed(tmp_path, field, value):
    fixture = _docs_placed(tmp_path)
    _rewrite_record(fixture[-1], field, value)
    run, transport = _retry_docs(fixture)
    with pytest.raises(PlacementExecutionError, match='placement-recovery-conflict'):
        run()
    assert transport.calls == []


def test_recovery_substituted_inserted_id_fails_closed(tmp_path):
    fixture = _docs_placed(tmp_path)
    _rewrite_record(fixture[-1], 'inserted_element_id', 'phantom-object')
    run, transport = _retry_docs(fixture)
    with pytest.raises(PlacementExecutionError, match='placement-recovery-stale'):
        run()
    assert transport.calls == []


def test_recovery_deleted_slides_image_fails_closed(tmp_path):
    fixture = _slides_placed(tmp_path)
    slide = fixture[1].presentations_store['pres-1']['slides'][0]
    slide['elements'] = [e for e in slide['elements'] if not e['objectId'].startswith('fake-inserted')]
    run, transport = _retry_slides(fixture)
    with pytest.raises(PlacementExecutionError, match='placement-recovery-stale'):
        run()
    assert transport.calls == []


def test_recovery_slides_image_wrong_container_fails_closed(tmp_path):
    fixture = _slides_placed(tmp_path)
    slides = fixture[1].presentations_store['pres-1']['slides']
    slide1, slide2 = slides
    image = next(e for e in slide1['elements'] if e['objectId'].startswith('fake-inserted'))
    slide1['elements'].remove(image)
    slide2['elements'].append(image)
    run, transport = _retry_slides(fixture)
    with pytest.raises(PlacementExecutionError, match='placement-recovery-stale'):
        run()
    assert transport.calls == []


def test_docs_insertion_without_persisted_inline_image_refused(tmp_path):
    docs, slides, drive, transport = _docs_harness(tmp_path)
    original = transport.insert_placement
    def vanishing(*, request):
        outcome = original(request=request)
        docs.documents_store['doc-1']['inline_objects'].clear()
        return outcome
    transport.insert_placement = vanishing
    receipts_dir = tmp_path / 'receipts'
    with pytest.raises(PlacementExecutionError, match='post-insertion-verification-failed'):
        _execute([_binding('worked-example')], artifact_type='docs', artifact_id='doc-1',
                 drive=drive, docs=docs, slides=slides, transport=transport,
                 receipts_dir=receipts_dir)
    assert load_placement_records(receipts_dir, KEY) == ()


def test_completion_backstop_rejects_substituted_asset_receipt(tmp_path):
    fixture = _docs_placed(tmp_path)
    _rewrite_record(fixture[-1], 'asset_id', 'forged-asset')
    with pytest.raises(PlacementExecutionError, match='not verified-placed'):
        require_all_required_visuals_placed(
            bindings=(fixture[3],), receipts_dir=str(fixture[-1]),
            idempotency_key=KEY, artifact_files={'worksheet': 'doc-1'},
        )


def test_timeout_orphan_cannot_be_silently_recovered(tmp_path):
    docs, slides, drive, _transport = _docs_harness(tmp_path)
    doc = docs.documents_store['doc-1']
    doc['paragraphs'] = ['Worksheet', '', 'Footer']
    doc['inline_objects'].append('unreceipted-image')
    binding = _binding('worked-example')
    receipt_dir = tmp_path / 'receipts'
    (outcome,) = _execute([binding], artifact_type='docs', artifact_id='doc-1',
                          drive=drive, docs=docs, slides=slides,
                          transport=FakePlacementTransport(docs=docs, slides=slides),
                          receipts_dir=receipt_dir)
    assert outcome.status == 'skipped-no-marker'
    with pytest.raises(PlacementExecutionError, match='not verified-placed'):
        require_all_required_visuals_placed(
            bindings=(binding,), receipts_dir=str(receipt_dir),
            idempotency_key=KEY, artifact_files={'worksheet': 'doc-1'},
        )


def test_recovered_slide_shape_substitution_is_not_a_verified_image(tmp_path):
    fixture = _slides_placed(tmp_path)
    slides = fixture[1]
    elements = slides.presentations_store['pres-1']['slides'][0]['elements']
    inserted = next(e for e in elements if e.get('image'))
    inserted['image'] = False
    inserted['text'] = 'innocent shape'
    run, transport = _retry_slides(fixture)
    with pytest.raises(PlacementExecutionError, match='placement-recovery-stale'):
        run()
    assert transport.calls == []


def test_recovered_slide_image_in_wrong_slide_is_not_verified(tmp_path):
    fixture = _slides_placed(tmp_path)
    slides = fixture[1]
    deck = slides.presentations_store['pres-1']['slides']
    image = next(e for e in deck[0]['elements'] if e.get('image'))
    deck[0]['elements'].remove(image)
    deck[1]['elements'].append(image)
    run, transport = _retry_slides(fixture)
    with pytest.raises(PlacementExecutionError, match='placement-recovery-stale'):
        run()
    assert transport.calls == []
