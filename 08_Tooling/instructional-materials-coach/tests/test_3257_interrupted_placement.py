"""Phase 2 #3257: unknown-outcome and verified-revision recovery safety.

Injected Docs/Slides/Drive fakes only; zero production writes.
"""
from __future__ import annotations
import json
import hashlib
import pytest
from instructional_materials_coach.connected_visual_placement import (
    PlacementExecutionError, require_all_required_visuals_placed,
)
from instructional_materials_coach.placement_receipts import (
    load_placement_records, placement_record_path,
)
from instructional_materials_coach.placement_transport import PlacementTransportError
from instructional_materials_coach.visual_placement import marker_for_role
from test_3257_connected_visual_placement import (
    FakeDocsService, FakeDriveService, FakeSlidesService, FakePlacementTransport,
    _binding, _docs_harness, _drive_metadata, _execute,
)

KEY = 'k'*64


def _run(bindings,docs,slides,drive,transport,receipts_dir,artifact_type='docs',artifact_id='doc-1'):
    return _execute(bindings,artifact_type=artifact_type,artifact_id=artifact_id,
                    drive=drive,docs=docs,slides=slides,transport=transport,
                    receipts_dir=receipts_dir)


def _fence(root,role,artifact_type='docs',artifact_id='doc-1'):
    # Independently calculate the shortened Windows-safe per-build fence.
    # Do not call the function under test to establish path equality.
    identity = json.dumps([artifact_type,artifact_id,role,'0'],sort_keys=True,separators=(',',':'))
    digest = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:48]
    build_digest = hashlib.sha256(KEY.encode('utf-8')).hexdigest()[:24]
    return root/('.attempts-'+build_digest)/(digest+'.json')


def test_timeout_after_docs_insertion_is_durable_and_blocks_retry(tmp_path):
    docs,slides,drive,tr = _docs_harness(tmp_path)
    original = tr.insert_placement
    def timed_out(*,request):
        original(request=request)
        raise PlacementTransportError('placement-transport-failed: simulated timeout')
    tr.insert_placement = timed_out
    binding = _binding('worked-example')
    root = tmp_path/'receipts'
    with pytest.raises(PlacementExecutionError,match='simulated timeout'):
        _run([binding],docs,slides,drive,tr,root)
    assert len(docs.documents_store['doc-1']['inline_objects']) == 1
    assert load_placement_records(root,KEY) == ()
    assert _fence(root,'worked-example').exists()
    retry = FakePlacementTransport(docs=docs,slides=slides)
    with pytest.raises(PlacementExecutionError,match='placement-reconciliation-required'):
        _run([binding],docs,slides,drive,retry,root)
    assert retry.calls == []
    with pytest.raises(PlacementExecutionError,match='placement-reconciliation-required'):
        require_all_required_visuals_placed(bindings=(binding,), receipts_dir=str(root),
            idempotency_key=KEY,artifact_files={'worksheet':'doc-1'})


def test_generic_transport_error_without_write_is_still_ambiguous(tmp_path):
    # A timeout can complete asynchronously AFTER the first readback.
    docs,slides,drive,tr = _docs_harness(tmp_path)
    def indeterminate(*,request):
        raise PlacementTransportError('placement-transport-failed: ambiguous timeout')
    tr.insert_placement = indeterminate
    root=tmp_path/'receipts'; binding=_binding('worked-example')
    with pytest.raises(PlacementExecutionError,match='ambiguous timeout'):
        _run([binding],docs,slides,drive,tr,root)
    assert _fence(root,'worked-example').exists()
    retry=FakePlacementTransport(docs=docs,slides=slides)
    with pytest.raises(PlacementExecutionError,match='placement-reconciliation-required'):
        _run([binding],docs,slides,drive,retry,root)
    assert retry.calls==[]


def test_crash_after_insertion_before_receipt_is_durable(tmp_path):
    docs,slides,drive,tr = _docs_harness(tmp_path)
    original = tr.insert_placement
    def interrupted(*,request):
        original(request=request)
        raise KeyboardInterrupt('simulated process crash')
    tr.insert_placement=interrupted
    root=tmp_path/'receipts'; binding=_binding('worked-example')
    with pytest.raises(KeyboardInterrupt):
        _run([binding],docs,slides,drive,tr,root)
    assert _fence(root,'worked-example').exists()
    retry=FakePlacementTransport(docs=docs,slides=slides)
    with pytest.raises(PlacementExecutionError,match='placement-reconciliation-required'):
        _run([binding],docs,slides,drive,retry,root)
    assert len(docs.documents_store['doc-1']['inline_objects']) == 1
    assert retry.calls == []


def test_known_no_mutation_failure_preserves_safe_retry(tmp_path):
    docs,slides,drive,tr=_docs_harness(tmp_path)
    tr._fail_for_roles.add('worked-example')
    root=tmp_path/'receipts'; binding=_binding('worked-example')
    with pytest.raises(PlacementExecutionError,match='placement-transport-failed'):
        _run([binding],docs,slides,drive,tr,root)
    assert not _fence(root,'worked-example').exists()
    fresh=FakePlacementTransport(docs=docs,slides=slides)
    (out,) = _run([binding],docs,slides,drive,fresh,root)
    assert out.status=='placed' and len(fresh.calls)==1
    assert not _fence(root,'worked-example').exists()


def test_partial_four_image_batch_blocks_orphan_but_never_duplicates(tmp_path):
    roles=['worked-example','comparison','diagram','reference']
    docs=FakeDocsService(); docs.add_document('doc-1',[marker_for_role(r) for r in roles])
    slides=FakeSlidesService();drive=FakeDriveService({'file-1':_drive_metadata('file-1')})
    tr=FakePlacementTransport(docs=docs,slides=slides)
    original=tr.insert_placement
    def crash_on_third(*,request):
        result=original(request=request)
        if len(tr.calls)==3:
            raise KeyboardInterrupt('crash on third')
        return result
    tr.insert_placement=crash_on_third
    root=tmp_path/'receipts';bs=[_binding(r) for r in roles]
    with pytest.raises(KeyboardInterrupt):
        _run(bs,docs,slides,drive,tr,root)
    assert len(docs.documents_store['doc-1']['inline_objects']) == 3
    assert len(load_placement_records(root,KEY)) == 2
    assert _fence(root,'diagram').exists()
    retry=FakePlacementTransport(docs=docs,slides=slides)
    with pytest.raises(PlacementExecutionError,match='placement-reconciliation-required'):
        _run(bs,docs,slides,drive,retry,root)
    # Preflight halts BEFORE completing the remaining image of the batch.
    assert retry.calls == []
    assert len(docs.documents_store['doc-1']['inline_objects'])==3
    assert len(load_placement_records(root,KEY))==2
    with pytest.raises(PlacementExecutionError,match='placement-reconciliation-required'):
        require_all_required_visuals_placed(bindings=bs,receipts_dir=str(root),
            idempotency_key=KEY,artifact_files={'worksheet':'doc-1'})


def test_shared_asset_two_roles_both_recover_from_distinct_receipts(tmp_path):
    docs=FakeDocsService();docs.add_document('doc-1',[marker_for_role('worked-example'),marker_for_role('comparison')])
    slides=FakeSlidesService();drive=FakeDriveService({'file-1':_drive_metadata('file-1')})
    root=tmp_path/'receipts';bs=[_binding('worked-example'),_binding('comparison')]
    first=_run(bs,docs,slides,drive,FakePlacementTransport(docs=docs,slides=slides),root)
    assert [o.status for o in first]==['placed','placed']
    retry=FakePlacementTransport(docs=docs,slides=slides)
    second=_run(bs,docs,slides,drive,retry,root)
    assert [o.status for o in second]==['recovered','recovered']
    assert retry.calls==[]


def test_external_edit_invalidates_historical_receipt(tmp_path):
    docs,slides,drive,tr=_docs_harness(tmp_path)
    root=tmp_path/'receipts';b=_binding('worked-example')
    _run([b],docs,slides,drive,tr,root)
    doc=docs.documents_store['doc-1'];doc['paragraphs'].append('EXTERNAL EDIT');doc['revisionId']='teacher-revision'
    with pytest.raises(PlacementExecutionError,match='placement-recovery-stale'):
        _run([b],docs,slides,drive,FakePlacementTransport(docs=docs,slides=slides),root)


def test_malformed_verified_receipt_store_never_recovers(tmp_path):
    docs,slides,drive,tr=_docs_harness(tmp_path)
    root=tmp_path/'receipts';b=_binding('worked-example')
    _run([b],docs,slides,drive,tr,root)
    placement_record_path(root,KEY).write_text('{',encoding='utf-8')
    with pytest.raises(PlacementExecutionError,match='placement-receipt-store-invalid'):
        _run([b],docs,slides,drive,FakePlacementTransport(docs=docs,slides=slides),root)


def test_duplicate_verified_receipts_refused(tmp_path):
    docs,slides,drive,tr=_docs_harness(tmp_path)
    root=tmp_path/'receipts';b=_binding('worked-example')
    _run([b],docs,slides,drive,tr,root)
    path=placement_record_path(root,KEY);payload=json.loads(path.read_text(encoding='utf-8'))
    payload['records'].append(dict(payload['records'][0]))
    path.write_text(json.dumps(payload),encoding='utf-8')
    with pytest.raises(PlacementExecutionError,match='duplicate/conflicting'):
        _run([b],docs,slides,drive,FakePlacementTransport(docs=docs,slides=slides),root)


def test_mutated_placement_receipt_id_and_drive_rejected(tmp_path):
    docs,slides,drive,tr=_docs_harness(tmp_path)
    root=tmp_path/'receipts';b=_binding('worked-example')
    _run([b],docs,slides,drive,tr,root)
    path=placement_record_path(root,KEY);payload=json.loads(path.read_text(encoding='utf-8'))
    payload['records'][0]['asset_id']='substituted-asset'
    payload['records'][0]['drive_file_id']='other-file'
    path.write_text(json.dumps(payload),encoding='utf-8')
    with pytest.raises(PlacementExecutionError,match='placement-recovery-conflict'):
        _run([b],docs,slides,drive,FakePlacementTransport(docs=docs,slides=slides),root)


def test_corrupted_attempt_cannot_be_retried_or_cleared(tmp_path):
    docs,slides,drive,tr=_docs_harness(tmp_path)
    original=tr.insert_placement
    def interrupted(*,request):
        original(request=request)
        raise KeyboardInterrupt('crash')
    tr.insert_placement=interrupted
    root=tmp_path/'receipts'; b=_binding('worked-example')
    with pytest.raises(KeyboardInterrupt):
        _run([b],docs,slides,drive,tr,root)
    _fence(root,'worked-example').write_text('bad json',encoding='utf-8')
    with pytest.raises(PlacementExecutionError,match='placement-attempt-invalid'):
        _run([b],docs,slides,drive,FakePlacementTransport(docs=docs,slides=slides),root)



def test_attempt_journal_path_bounded_and_build_scoped(tmp_path):
    """Different builds never share unresolved fences; use short Windows-safe paths."""
    from instructional_materials_coach.placement_receipts import (
        placement_attempt_path, begin_placement_attempt, assert_no_unresolved_placement_attempts,
        PlacementStoreIntegrityError,
    )
    key_two = 'z'*64
    common = dict(artifact_type='docs',artifact_id='doc-1',role_id='worked-example',slot_id='0')
    one = placement_attempt_path(tmp_path,KEY,**common)
    two = placement_attempt_path(tmp_path,key_two,**common)
    assert one != two
    assert one.parent != two.parent
    assert one == _fence(tmp_path,'worked-example')
    assert len(one.name) <= 53
    assert len(one.parent.name) <= 34
    attempt = dict(common, asset_id='asset-1', drive_file_id='file-1',
        source_plan_id='plan-1', content_identity={'contract_version':'fake'},
        artifact_revision_id='rev-1',marker='{{visual:worked-example}}',container_id='body')
    begin_placement_attempt(tmp_path,KEY,attempt)
    assert one.exists()
    with pytest.raises(PlacementStoreIntegrityError,match='reconciliation-required'):
        assert_no_unresolved_placement_attempts(tmp_path,KEY)
    # Build two has no outstanding work, even when build one is interrupted.
    assert_no_unresolved_placement_attempts(tmp_path,key_two)
def test_optional_only_interrupted_visual_blocks_completion(tmp_path):
    """An optional orphan is not permission to mark a build as complete."""
    from dataclasses import replace
    docs, slides, drive, transport = _docs_harness(tmp_path)
    original = transport.insert_placement

    def interrupted(*, request):
        original(request=request)
        raise KeyboardInterrupt('optional orphan after write')

    transport.insert_placement = interrupted
    optional = replace(_binding('worked-example'), required=False)
    root = tmp_path / 'receipts'
    with pytest.raises(KeyboardInterrupt):
        _run([optional], docs, slides, drive, transport, root)
    assert _fence(root, 'worked-example').exists()
    with pytest.raises(PlacementExecutionError, match='placement-reconciliation-required'):
        require_all_required_visuals_placed(
            bindings=(optional,), receipts_dir=str(root), idempotency_key=KEY,
            artifact_files={'worksheet': 'doc-1'},
        )


def test_abandoned_role_attempt_preflights_before_new_insertion(tmp_path):
    """Removing the orphaned role from the current plan cannot hide the write."""
    docs = FakeDocsService()
    docs.add_document('doc-1', [marker_for_role('worked-example'), marker_for_role('comparison')])
    slides = FakeSlidesService()
    drive = FakeDriveService({'file-1': _drive_metadata('file-1')})
    transport = FakePlacementTransport(docs=docs, slides=slides)
    original = transport.insert_placement

    def interrupted(*, request):
        original(request=request)
        raise KeyboardInterrupt('first role interrupted')

    transport.insert_placement = interrupted
    root = tmp_path / 'receipts'
    with pytest.raises(KeyboardInterrupt):
        _run([_binding('worked-example')], docs, slides, drive, transport, root)
    assert _fence(root, 'worked-example').exists()
    retry = FakePlacementTransport(docs=docs, slides=slides)
    with pytest.raises(PlacementExecutionError, match='placement-reconciliation-required'):
        _run([_binding('comparison')], docs, slides, drive, retry, root)
    assert retry.calls == []
    assert len(docs.documents_store['doc-1']['inline_objects']) == 1


def test_matching_receipt_after_crash_can_clear_only_its_own_fence(tmp_path, monkeypatch):
    """Crash after verified receipt, before fence removal, stays recoverable."""
    import instructional_materials_coach.connected_visual_placement as placement

    docs, slides, drive, transport = _docs_harness(tmp_path)
    root = tmp_path / 'receipts'
    binding = _binding('worked-example')
    original_clear = placement.clear_placement_attempt

    def crash_before_clear(*args, **kwargs):
        raise KeyboardInterrupt('crash between receipt and clearing journal')

    monkeypatch.setattr(placement, 'clear_placement_attempt', crash_before_clear)
    with pytest.raises(KeyboardInterrupt, match='crash between receipt'):
        _run([binding], docs, slides, drive, transport, root)
    assert _fence(root, 'worked-example').exists()
    assert len(load_placement_records(root, KEY)) == 1
    monkeypatch.setattr(placement, 'clear_placement_attempt', original_clear)
    retry = FakePlacementTransport(docs=docs, slides=slides)
    (result,) = _run([binding], docs, slides, drive, retry, root)
    assert result.status == 'recovered'
    assert retry.calls == []
    assert not _fence(root, 'worked-example').exists()
