from __future__ import annotations
import ast
import copy
import json
from pathlib import Path
import pytest
import instructional_workflow_contracts.artifact_manifest as manifest_module
from instructional_workflow_contracts import AuthorityEvidence, ContractValidationError, ValidationStatus, canonical_json_bytes, canonical_size, resolve_status, sha256_hex
from instructional_workflow_contracts.artifact_manifest import ACCESS_STATES, CONTEXT_FLAGS, MAX_ASSETS, MAX_CONTEXT_FLAGS, MAX_QUALITY_ROWS, MAX_REFERENCES, MAX_REVISIONS, MAX_RISK_FINDINGS, MAX_TRANSFORMATION_FLAGS, TRANSFORMATIONS, artifact_manifest_idempotency_key, artifact_manifest_source_fingerprint, validate_artifact_manifest

def _candidate(candidate_id: str='candidate-1', relationship: str='exact-duplicate', disposition: str='canonical', canonical_ref: str | None=None, compatible: bool=True, conflicting: bool=False) -> dict[str, object]:
    return {'candidate_id': candidate_id, 'relationship': relationship, 'disposition': disposition, 'canonical_asset_ref': canonical_ref, 'comparison_evidence': 'supplied comparison evidence', 'confidence': 0.95, 'compatible': compatible, 'conflicting': conflicting}

def _revision(index: int=1, rollback_kind: str='retained-prior-file') -> dict[str, object]:
    verified = rollback_kind in {'retained-prior-file', 'exported-backup'}
    return {'revision_id': f'revision-{index}', 'predecessor_ref': f'manifest-{index - 1}' if index > 1 else 'manifest-0', 'operation': 'revise-existing', 'trigger': 'source change evidence', 'changed_sections': ['practice'], 'preserved_sections': ['directions'], 'resulting_file_ref': f'file-{index}', 'reviewer_owner': 'instructional-materials-coach', 'timestamp': '2026-07-30T00:00:00Z', 'rollback_kind': rollback_kind, 'rollback_ref': f'rollback-{index}' if verified else None, 'rollback_verified': verified}

def _asset(index: int=1) -> dict[str, object]:
    return {'asset_id': f'asset-{index}', 'stable_ref': f'asset-ref-{index}', 'content_fingerprint': 'c' * 64, 'perceptual_match_evidence': None, 'duplicate_group_id': None, 'duplicate_relationship': 'unique', 'disposition': 'canonical', 'canonical_asset_ref': None, 'comparison_evidence': 'supplied comparison evidence', 'confidence': 1.0, 'rights_classification': 'permission-documented', 'rights_basis': 'permission-evidence', 'warning_signals': [], 'privacy_observations': [], 'privacy_mitigation': 'none', 'privacy_resolved': True, 'residual_privacy_risk': False, 'content_findings': [], 'repair_source_status': 'not-needed', 'direct_use_status': 'student-ready', 'correction_requirement': None, 'replacement_required': False, 'transformations': [], 'required_context_flags': [], 'preserved_context_flags': [], 'context_preservation_complete': True}

def valid_manifest() -> dict[str, object]:
    value: dict[str, object] = {'identity': {'contract_version': 'curriculum-artifact-manifest-v1', 'manifest_id': 'manifest-1', 'record_revision': 1, 'created_at': '2026-07-30T00:00:00Z', 'modified_at': '2026-07-30T00:00:00Z', 'verified_at': '2026-07-30T00:00:00Z', 'source_fingerprint': '0' * 64}, 'requirement_reference': {'requirement_id': 'requirement-1', 'contract_version': 'curriculum-material-requirement-v1', 'record_revision': 1, 'fingerprint': 'a' * 64}, 'artifact': {'artifact_type': 'worksheet', 'mime_type': 'application/pdf', 'observed_sections': ['directions', 'practice']}, 'external_identity': {'provider': 'google-drive', 'file_id': 'file-1', 'drive_id': 'drive-1', 'resource_key_required': True, 'resource_key': 'resource-1', 'parent_folder_ref': 'folder-1', 'exact_reference': 'drive:file-1', 'web_view_link': 'https://example.invalid/file-1', 'external_revision': 'drive-revision-1', 'modified_time': '2026-07-30T00:00:00Z', 'last_verified_at': '2026-07-30T00:00:00Z', 'verification_scope': 'shared-drive', 'access_state': 'verified', 'trashed': False}, 'source_snapshot': {'handoff_id': 'handoff-1', 'source_fingerprint': 'b' * 64, 'dependency_fingerprint': 'd' * 64, 'dependency_keys': ['source.unit', 'material.requirement'], 'dependency_values': {'source.unit': 'unit-1', 'material.requirement': 'requirement-1'}, 'source_changed': False}, 'operation': {'kind': 'discover-existing', 'idempotency_key': 'manifest-requirement-operation-target', 'approved_request_id': None, 'approved_scope': None, 'current_file_ref': None, 'template_ref': None, 'template_permission_state': None, 'discovery_evidence': ['supplied provider/file identity']}, 'duplicates': {'candidates': [], 'selected_candidate_ref': None}, 'lineage': {'revisions': [], 'predecessor_ref': None, 'successor_ref': None, 'supersession_reason': None}, 'statuses': {'quality_state': 'pass', 'teacher_approval': 'approved', 'classroom_readiness': 'ready', 'production_state': 'not-authorized', 'publication_state': 'not-published', 'sharing_state': 'private-observed'}, 'quality_rows': [{'row_id': 'quality-1', 'state': 'pass', 'reason_codes': []}], 'assets': [_asset()], 'references': [{'reference_id': 'reference-1', 'kind': 'material-requirement', 'stable_ref': 'requirement-1', 'fingerprint': 'e' * 64}], 'custom_properties': {'manifest_id': 'manifest-1', 'requirement_id': 'requirement-1', 'contract_version': 'curriculum-artifact-manifest-v1', 'idempotency_key': 'manifest-requirement-operation-target'}, 'authority': {'execution_authorized': False, 'external_write_authorized': False, 'production_authorized': False, 'publication_authorized': False, 'side_effects_performed': False}}
    _refresh(value)
    return value

def _refresh(value: dict[str, object]) -> None:
    snapshot = value['source_snapshot']
    snapshot['dependency_fingerprint'] = sha256_hex({'dependency_keys': sorted(snapshot['dependency_keys']), 'dependency_values': snapshot['dependency_values']})
    key = artifact_manifest_idempotency_key(value)
    value['operation']['idempotency_key'] = key
    value['custom_properties']['idempotency_key'] = key
    value['identity']['source_fingerprint'] = artifact_manifest_source_fingerprint(value)

def _result(value: dict[str, object]):
    _refresh(value)
    return validate_artifact_manifest(value)

def test_valid_discovered_manifest_is_deterministic_immutable_and_authority_false() -> None:
    supplied = valid_manifest()
    before = copy.deepcopy(supplied)
    first = validate_artifact_manifest(supplied)
    second = validate_artifact_manifest(copy.deepcopy(supplied))
    assert first.status is ValidationStatus.VALID
    assert first.record is not None and second.record is not None
    assert first.record.fingerprint == second.record.fingerprint
    assert first.authority == first.record.authority == AuthorityEvidence()
    assert first.record.to_dict()['authority'] == {'execution_authorized': False, 'external_write_authorized': False, 'production_authorized': False, 'publication_authorized': False, 'side_effects_performed': False}
    assert canonical_size(first.record.to_dict()) <= 16 * 1024
    assert supplied == before

def test_valid_approved_create_remains_non_authorizing() -> None:
    value = valid_manifest()
    value['external_identity'].update({'provider': 'local-reference', 'drive_id': None, 'resource_key_required': False, 'resource_key': None, 'verification_scope': 'local-reference'})
    value['operation'].update({'kind': 'create-new-approved', 'approved_request_id': 'request-1', 'discovery_evidence': []})
    result = _result(value)
    assert result.status is ValidationStatus.VALID
    assert result.authority == AuthorityEvidence()

@pytest.mark.parametrize(('provider', 'expected_status'), [('google-drive', ValidationStatus.VALID), ('local-reference', ValidationStatus.VALID), ('other-manual-review', ValidationStatus.MANUAL_REVIEW_REQUIRED)])
def test_every_provider_classification_is_explicit(provider: str, expected_status: ValidationStatus) -> None:
    value = valid_manifest()
    value['external_identity'].update({'provider': provider, 'drive_id': 'drive-1' if provider == 'google-drive' else None, 'resource_key_required': provider == 'google-drive', 'resource_key': 'resource-1' if provider == 'google-drive' else None, 'verification_scope': 'shared-drive' if provider == 'google-drive' else 'local-reference'})
    if provider == 'other-manual-review':
        value['external_identity']['access_state'] = 'unverified'
        value['statuses']['classroom_readiness'] = 'manual-review-required'
        value['assets'][0]['direct_use_status'] = 'manual-review'
    result = _result(value)
    assert result.status is expected_status

def test_requirement_dependency_and_idempotency_evidence_fail_closed() -> None:
    requirement = valid_manifest()
    requirement['requirement_reference']['contract_version'] = 'future-requirement-v2'
    assert 'artifact-incompatible-requirement' in _result(requirement).reason_codes
    malformed = valid_manifest()
    malformed['requirement_reference']['fingerprint'] = 'not-a-sha'
    assert validate_artifact_manifest(malformed).status is ValidationStatus.INVALID
    dependency = valid_manifest()
    dependency['source_snapshot']['dependency_fingerprint'] = 'f' * 64
    dependency['identity']['source_fingerprint'] = artifact_manifest_source_fingerprint(dependency)
    assert 'dependency-invalid' in validate_artifact_manifest(dependency).reason_codes
    idempotency = valid_manifest()
    stable = artifact_manifest_idempotency_key(idempotency)
    idempotency['identity']['created_at'] = '2026-07-30T02:00:00Z'
    assert artifact_manifest_idempotency_key(idempotency) == stable
    idempotency['operation']['idempotency_key'] = 'f' * 64
    idempotency['custom_properties']['idempotency_key'] = 'f' * 64
    idempotency['identity']['source_fingerprint'] = artifact_manifest_source_fingerprint(idempotency)
    assert 'artifact-idempotency-conflict' in validate_artifact_manifest(idempotency).reason_codes

@pytest.mark.parametrize('access_state', sorted(ACCESS_STATES - {'verified'}))
def test_access_states_remain_distinct_and_route_to_manual_review(access_state: str) -> None:
    value = valid_manifest()
    value['external_identity']['access_state'] = access_state
    value['external_identity']['trashed'] = access_state == 'trashed'
    value['statuses']['classroom_readiness'] = 'manual-review-required'
    value['assets'][0]['direct_use_status'] = 'manual-review'
    result = _result(value)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert 'artifact-access-manual-review' in result.reason_codes
    assert result.record is not None
    assert result.record.to_dict()['external_identity']['access_state'] == access_state

def test_shared_drive_resource_key_and_url_only_identity_fail_closed() -> None:
    missing_drive = valid_manifest()
    missing_drive['external_identity']['drive_id'] = None
    assert 'artifact-missing-drive-id' in _result(missing_drive).reason_codes
    missing_key = valid_manifest()
    missing_key['external_identity']['resource_key'] = None
    assert 'artifact-missing-resource-key' in _result(missing_key).reason_codes
    url_only = valid_manifest()
    url_only['external_identity']['file_id'] = None
    assert 'artifact-url-only-identity' in _result(url_only).reason_codes

def test_evidence_only_timestamps_and_display_link_do_not_define_source_identity() -> None:
    first = valid_manifest()
    second = copy.deepcopy(first)
    second['identity']['created_at'] = '2026-07-30T01:00:00Z'
    second['external_identity']['web_view_link'] = 'https://example.invalid/other'
    second['external_identity']['modified_time'] = '2026-07-30T01:00:00Z'
    assert artifact_manifest_source_fingerprint(first) == artifact_manifest_source_fingerprint(second)

@pytest.mark.parametrize(('kind', 'mutation', 'reason'), [('discover-existing', lambda value: value['operation'].__setitem__('discovery_evidence', []), 'artifact-missing-discovery-evidence'), ('revise-existing', lambda value: value['operation'].__setitem__('current_file_ref', None), 'artifact-invalid-lifecycle'), ('copy-approved-template', lambda value: value['operation'].__setitem__('template_ref', None), 'template-unverified-permission'), ('create-new-approved', lambda value: value['operation'].__setitem__('approved_request_id', None), 'artifact-invalid-lifecycle'), ('supersede-with-new-version', lambda value: value['lineage'].__setitem__('predecessor_ref', None), 'artifact-invalid-lifecycle')])
def test_invalid_operation_transitions(kind: str, mutation, reason: str) -> None:
    value = valid_manifest()
    value['operation']['kind'] = kind
    if kind == 'revise-existing':
        value['operation']['approved_scope'] = 'sections:practice'
        value['operation']['current_file_ref'] = 'file-1'
        value['lineage']['revisions'] = [_revision()]
    elif kind == 'copy-approved-template':
        value['operation']['template_ref'] = 'template-1'
        value['operation']['template_permission_state'] = 'permission-documented'
    elif kind == 'create-new-approved':
        value['operation']['approved_request_id'] = 'request-1'
    elif kind == 'supersede-with-new-version':
        value['operation']['current_file_ref'] = 'file-1'
        value['lineage'].update({'predecessor_ref': 'manifest-0', 'successor_ref': 'manifest-2', 'supersession_reason': 'new canonical version', 'revisions': [_revision()]})
    mutation(value)
    assert reason in _result(value).reason_codes

def test_reuse_candidate_is_unique_or_routes_to_manual_review() -> None:
    valid = valid_manifest()
    valid['operation'].update({'kind': 'reuse-existing', 'current_file_ref': 'file-1', 'discovery_evidence': []})
    valid['duplicates'] = {'candidates': [_candidate()], 'selected_candidate_ref': 'candidate-1'}
    assert _result(valid).status is ValidationStatus.VALID
    ambiguous = copy.deepcopy(valid)
    ambiguous['duplicates'] = {'candidates': [_candidate('candidate-1'), _candidate('candidate-2')], 'selected_candidate_ref': 'candidate-1'}
    result = _result(ambiguous)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert 'artifact-ambiguous-reuse-candidate' in result.reason_codes

def test_duplicate_dispositions_require_canonical_reference() -> None:
    for relationship, disposition in (('near-duplicate', 'alternate'), ('exact-duplicate', 'archive-candidate')):
        value = valid_manifest()
        asset = value['assets'][0]
        asset['duplicate_relationship'] = relationship
        asset['disposition'] = disposition
        assert 'asset-missing-canonical-reference' in _result(value).reason_codes
        asset['canonical_asset_ref'] = 'asset-canonical'
        assert _result(value).status is ValidationStatus.VALID

def test_rollback_truth_is_preserved() -> None:
    value = valid_manifest()
    value['operation'].update({'kind': 'revise-existing', 'current_file_ref': 'file-1', 'approved_scope': 'sections:practice', 'discovery_evidence': []})
    value['lineage']['revisions'] = [_revision(1, 'drive-revision-only')]
    result = _result(value)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert 'artifact-rollback-unverified' in result.reason_codes
    value['lineage']['revisions'] = [_revision()]
    assert _result(value).status is ValidationStatus.VALID

def test_revision_lineage_preserves_append_order_and_rejects_contradictions() -> None:
    value = valid_manifest()
    value['operation'].update({'kind': 'revise-existing', 'current_file_ref': 'file-2', 'approved_scope': 'all-sections', 'discovery_evidence': []})
    first = _revision(1)
    second = _revision(2)
    second['timestamp'] = '2026-07-30T01:00:00Z'
    value['lineage']['revisions'] = [first, second]
    result = _result(value)
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    assert [row['revision_id'] for row in result.record.to_dict()['lineage']['revisions']] == ['revision-1', 'revision-2']
    second['timestamp'] = '2026-07-29T23:00:00Z'
    assert 'artifact-contradictory-lineage' in _result(value).reason_codes
    second['timestamp'] = '2026-07-30T01:00:00Z'
    second['resulting_file_ref'] = first['resulting_file_ref']
    assert 'artifact-contradictory-lineage' in _result(value).reason_codes

def test_full_manifest_custom_property_and_conflicting_compact_key_fail() -> None:
    full = valid_manifest()
    full['custom_properties']['manifest'] = 'full manifest text'
    assert 'artifact-custom-property-full-manifest' in _result(full).reason_codes
    conflict = valid_manifest()
    conflict['custom_properties']['manifest_id'] = 'other-manifest'
    assert 'artifact-custom-property-conflict' in _result(conflict).reason_codes

def test_statuses_do_not_collapse_into_authority() -> None:
    value = valid_manifest()
    value['statuses'].update({'teacher_approval': 'approved', 'production_state': 'authorized-evidence-only', 'publication_state': 'published-observed', 'sharing_state': 'shared-observed'})
    result = _result(value)
    assert result.status is ValidationStatus.VALID
    assert result.authority == AuthorityEvidence()
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload['statuses']['publication_state'] == 'published-observed'
    assert payload['authority']['publication_authorized'] is False

def test_failed_quality_rows_block_passing_or_classroom_ready_status() -> None:
    value = valid_manifest()
    value['quality_rows'] = [{'row_id': 'quality-fail', 'state': 'fail', 'reason_codes': ['quality-unresolved-row']}]
    assert 'quality-status-contradiction' in _result(value).reason_codes
    value['statuses']['quality_state'] = 'fail'
    assert 'readiness-incompatible-quality' in _result(value).reason_codes

def test_warning_signal_cropping_never_establishes_cleared_rights() -> None:
    value = valid_manifest()
    asset = value['assets'][0]
    asset['warning_signals'] = ['watermark', 'brand']
    asset['rights_classification'] = 'permission-documented'
    asset['rights_basis'] = 'crop-or-hide-signal'
    asset['transformations'] = ['crop']
    assert 'asset-rights-not-cleared-by-crop' in _result(value).reason_codes

def test_unresolved_privacy_routes_to_manual_review_and_cannot_be_called_resolved() -> None:
    value = valid_manifest()
    asset = value['assets'][0]
    asset['privacy_observations'] = ['names', 'profiles']
    asset['privacy_mitigation'] = 'blur-or-redact'
    asset['privacy_resolved'] = False
    asset['residual_privacy_risk'] = True
    result = _result(value)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert 'asset-unresolved-privacy-risk' in result.reason_codes
    asset['privacy_resolved'] = True
    assert 'asset-privacy-contradiction' in _result(value).reason_codes

def test_malformed_or_answer_revealing_content_blocks_student_ready() -> None:
    for finding in ('malformed-text', 'answer-revealing-content'):
        value = valid_manifest()
        asset = value['assets'][0]
        asset['content_findings'] = [finding]
        asset['repair_source_status'] = 'required'
        asset['correction_requirement'] = 'repair supplied text'
        assert 'quality-unresolved-content' in _result(value).reason_codes

def test_context_preservation_and_transformation_categories_remain_explicit() -> None:
    value = valid_manifest()
    asset = value['assets'][0]
    asset['transformations'] = ['crop', 'rotate', 'cleanup']
    asset['required_context_flags'] = ['labels', 'arrows', 'comparison-groups', 'response-areas', 'interface-identity', 'environmental-setting', 'meaningful-order']
    asset['preserved_context_flags'] = list(asset['required_context_flags'])
    assert _result(value).status is ValidationStatus.VALID
    asset['preserved_context_flags'] = ['labels']
    assert 'asset-context-not-preserved' in _result(value).reason_codes

def test_authority_values_cannot_be_true() -> None:
    for key in valid_manifest()['authority']:
        value = valid_manifest()
        value['authority'][key] = True
        assert 'authority-invalid' in _result(value).reason_codes

def test_revision_quality_reference_and_asset_count_bounds() -> None:
    revisions = valid_manifest()
    revisions['operation'].update({'kind': 'revise-existing', 'current_file_ref': 'file-1', 'approved_scope': 'all-sections', 'discovery_evidence': []})
    revisions['lineage']['revisions'] = [_revision(i + 1) for i in range(MAX_REVISIONS)]
    exact = _result(revisions)
    assert exact.details != ('revisions exceed their collection bound',)
    revisions['lineage']['revisions'].append(_revision(MAX_REVISIONS + 1))
    assert _result(revisions).details == ('revisions exceed their collection bound',)
    quality = valid_manifest()
    quality['quality_rows'] = [{'row_id': f'quality-{i}', 'state': 'pass', 'reason_codes': []} for i in range(MAX_QUALITY_ROWS)]
    assert _result(quality).status is ValidationStatus.VALID
    quality['quality_rows'].append({'row_id': 'quality-over', 'state': 'pass', 'reason_codes': []})
    assert _result(quality).details == ('quality rows exceed their collection bound',)
    references = valid_manifest()
    references['references'] = [{'reference_id': f'r-{i}', 'kind': 'source', 'stable_ref': f'source-{i}', 'fingerprint': 'f' * 64} for i in range(MAX_REFERENCES)]
    assert _result(references).details != ('references exceed their collection bound',)
    references['references'].append({'reference_id': 'r-over', 'kind': 'source', 'stable_ref': 'source-over', 'fingerprint': 'f' * 64})
    assert _result(references).details == ('references exceed their collection bound',)
    assets = valid_manifest()
    assets['assets'] = [_asset(i + 1) for i in range(MAX_ASSETS)]
    assert _result(assets).details != ('assets exceed their collection bound',)
    assets['assets'].append(_asset(MAX_ASSETS + 1))
    assert _result(assets).details == ('assets exceed their collection bound',)

def test_risk_and_transformation_bounds_truthfully_reflect_finite_vocabularies() -> None:
    value = valid_manifest()
    asset = value['assets'][0]
    asset['privacy_observations'] = ['identifiable-people', 'names', 'profiles', 'account-details', 'notifications', 'dates', 'locations', 'thumbnails', 'messages', 'comments', 'reactions', 'social-identities']
    asset['privacy_mitigation'] = 'replace'
    asset['privacy_resolved'] = True
    assert _result(value).status is ValidationStatus.VALID
    asset['privacy_observations'] = ['names'] * (MAX_RISK_FINDINGS + 1)
    assert 'handoff-oversized' in _result(value).reason_codes
    value = valid_manifest()
    asset = value['assets'][0]
    asset['transformations'] = sorted(TRANSFORMATIONS)
    asset['direct_use_status'] = 'manual-review'
    value['statuses']['classroom_readiness'] = 'manual-review-required'
    assert _result(value).status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    asset['transformations'] = ['crop'] * (MAX_TRANSFORMATION_FLAGS + 1)
    assert 'handoff-oversized' in _result(value).reason_codes
    value = valid_manifest()
    asset = value['assets'][0]
    asset['required_context_flags'] = sorted(CONTEXT_FLAGS)
    asset['preserved_context_flags'] = sorted(CONTEXT_FLAGS)
    assert _result(value).status is ValidationStatus.VALID
    asset['required_context_flags'] = ['labels'] * (MAX_CONTEXT_FLAGS + 1)
    assert 'handoff-oversized' in _result(value).reason_codes

def _raw_canonical_size(value: object) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8'))

def _fit_bytes(target: int) -> dict[str, object]:
    payload: dict[str, object] = {'identity': {'source_fingerprint': '0' * 64}, 'padding': []}
    padding = payload['padding']
    while _raw_canonical_size(payload) < target:
        current = _raw_canonical_size(payload)
        prefix = f'item-{len(padding):03d}-'
        padding.append(prefix + 'x' * max(1, min(500 - len(prefix), target - current)))
        overshoot = _raw_canonical_size(payload) - target
        if overshoot > 0:
            padding[-1] = padding[-1][:-overshoot]
    assert _raw_canonical_size(payload) == target
    return payload

def test_exact_input_bound_and_one_over_use_shared_cw5a_validation() -> None:
    payload = _fit_bytes(64 * 1024)
    assert artifact_manifest_source_fingerprint(payload)
    payload['padding'][-1] += 'x'
    with pytest.raises(ContractValidationError) as caught:
        artifact_manifest_source_fingerprint(payload)
    assert caught.value.reason_code == 'handoff-oversized'

def test_result_bound_rejects_large_valid_shape_before_authority_changes() -> None:
    value = valid_manifest()
    value['quality_rows'] = [{'row_id': f'quality-{i}', 'state': 'manual-review', 'reason_codes': ['quality-' + 'a' * 100, 'quality-' + 'b' * 100, 'quality-' + 'c' * 100]} for i in range(MAX_QUALITY_ROWS)]
    value['statuses']['quality_state'] = 'manual-review'
    value['statuses']['classroom_readiness'] = 'manual-review-required'
    value['assets'][0]['direct_use_status'] = 'manual-review'
    result = _result(value)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ('handoff-oversized',)
    assert result.authority == AuthorityEvidence()

class HostileMapping(dict):

    def __iter__(self):
        raise AssertionError('hostile iterator executed')

class HostileString(str):
    pass

def test_hostile_custom_objects_fail_without_executing_behavior() -> None:
    assert validate_artifact_manifest(HostileMapping()).status is ValidationStatus.INVALID
    value = valid_manifest()
    value['identity']['manifest_id'] = HostileString('manifest-1')
    assert 'handoff-wrong-type' in validate_artifact_manifest(value).reason_codes

def test_shared_cw5a_helpers_are_used(monkeypatch: pytest.MonkeyPatch) -> None:
    value = valid_manifest()
    calls = {'normalize': 0, 'fingerprint': 0, 'freeze': 0, 'stable_id': 0}
    original_normalize = manifest_module.validate_and_normalize_json
    original_fingerprint = manifest_module.sha256_hex
    original_freeze = manifest_module.freeze_json
    original_stable = manifest_module.validate_stable_id

    def normalize_spy(raw: object, *, max_bytes: int):
        calls['normalize'] += 1
        return original_normalize(raw, max_bytes=max_bytes)

    def fingerprint_spy(raw: object) -> str:
        calls['fingerprint'] += 1
        return original_fingerprint(raw)

    def freeze_spy(raw: object):
        calls['freeze'] += 1
        return original_freeze(raw)

    def stable_spy(raw: object, name: str='stable_id'):
        calls['stable_id'] += 1
        return original_stable(raw, name)
    monkeypatch.setattr(manifest_module, 'validate_and_normalize_json', normalize_spy)
    monkeypatch.setattr(manifest_module, 'sha256_hex', fingerprint_spy)
    monkeypatch.setattr(manifest_module, 'freeze_json', freeze_spy)
    monkeypatch.setattr(manifest_module, 'validate_stable_id', stable_spy)
    assert validate_artifact_manifest(value).status is ValidationStatus.VALID
    assert all((count > 0 for count in calls.values()))

def test_domain_reasons_do_not_expand_governed_status_resolution() -> None:
    with pytest.raises(ContractValidationError) as caught:
        resolve_status(('artifact-access-manual-review',))
    assert caught.value.reason_code == 'handoff-invalid'

def test_no_duplicate_generic_framework_or_import_side_effects() -> None:
    path = Path(__file__).parents[1] / 'src' / 'instructional_workflow_contracts' / 'artifact_manifest.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    imports: set[str] = set()
    classes: set[str] = set()
    functions: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update((alias.name for alias in node.names))
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or '')
        elif isinstance(node, ast.ClassDef):
            classes.add(node.name)
        elif isinstance(node, ast.FunctionDef):
            functions.add(node.name)
        elif isinstance(node, ast.Call):
            calls.add(node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else '')
    assert imports <= {'__future__', 'typing', 'common'}
    assert classes.isdisjoint({'AuthorityEvidence', 'ValidationResult', 'ValidationStatus', 'ValidatedRecord'})
    assert functions.isdisjoint({'canonical_json_bytes', 'canonical_size', 'sha256_hex', 'freeze_json', 'sanitize_detail'})
    assert calls.isdisjoint({'open', 'getenv', 'Popen', 'run', 'system', 'basicConfig', 'register', 'import_module', 'eval', 'exec'})

def test_observed_sections_are_required_and_normalized() -> None:
    value = valid_manifest()
    result = _result(value)
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    assert result.record.to_dict()['artifact']['observed_sections'] == ['directions', 'practice']

def test_missing_observed_sections_fail_closed() -> None:
    value = valid_manifest()
    del value['artifact']['observed_sections']
    assert 'artifact-missing-required-field' in _result(value).reason_codes

def test_empty_observed_sections_are_allowed() -> None:
    value = valid_manifest()
    value['artifact']['observed_sections'] = []
    assert _result(value).status is ValidationStatus.VALID

def test_observed_sections_reject_duplicates_and_oversized_lists() -> None:
    duplicated = valid_manifest()
    duplicated['artifact']['observed_sections'] = ['directions', 'directions']
    assert 'handoff-duplicate' in _result(duplicated).reason_codes
    oversized = valid_manifest()
    oversized['artifact']['observed_sections'] = [f'section-{index}' for index in range(manifest_module.MAX_OBSERVED_SECTIONS + 1)]
    assert 'handoff-oversized' in _result(oversized).reason_codes

def test_observed_sections_bound_is_finite() -> None:
    assert manifest_module.MAX_OBSERVED_SECTIONS == 32

# Issue #3249 regression: contract round-trip / canonicalization.
#
# These tests enter through the real producer path: inputs are built as plain
# JSON-like documents, signed with artifact_manifest_source_fingerprint (plus
# the dependency/idempotency evidence the producer supplies), validated,
# serialized with record.to_dict(), and revalidated. Fixtures are deliberately
# non-canonical so the suite can see the defect the earlier baseline missed
# (fixtures were already in canonical order).

FIXTURES_3249 = Path(__file__).parent / "fixtures" / "instructional_workflow_contracts"


def _noncanonical_manifest() -> dict[str, object]:
    """Build a valid manifest with non-canonical list order (real producer)."""
    value = valid_manifest()
    value["artifact"]["observed_sections"] = ["practice", "directions"]  # type: ignore[index]
    value["source_snapshot"]["dependency_keys"] = [  # type: ignore[index]
        "material.requirement",
        "source.unit",
    ]
    value["operation"]["discovery_evidence"] = ["evidence-b", "evidence-a"]  # type: ignore[index]
    value["assets"] = list(reversed(value["assets"]))  # type: ignore[arg-type]
    _refresh(value)
    return value


def _manifest_round_trip(value: dict[str, object]):
    first = validate_artifact_manifest(value)
    assert first.status is ValidationStatus.VALID, first.reason_codes
    assert first.record is not None
    payload = first.record.to_dict()
    second = validate_artifact_manifest(copy.deepcopy(payload))
    assert second.status is ValidationStatus.VALID, second.reason_codes
    assert second.record is not None
    assert second.record.fingerprint == first.record.fingerprint
    # The canonical form is a fixed point: serializing it again changes nothing.
    assert second.record.to_dict() == payload
    return first, second


def test_round_trip_non_canonical_manifest_is_valid_and_fingerprint_stable() -> None:
    _manifest_round_trip(_noncanonical_manifest())


def test_manifest_permutation_round_trip_property() -> None:
    """Every permutation of order-insensitive lists yields VALID + equal fingerprint."""
    unsigned = _noncanonical_manifest()
    unsigned["identity"]["source_fingerprint"] = "0" * 64  # type: ignore[index]
    expected_result = validate_artifact_manifest(_noncanonical_manifest())
    assert expected_result.status is ValidationStatus.VALID
    assert expected_result.record is not None
    expected = expected_result.record.fingerprint

    paths = (
        ("artifact", "observed_sections"),
        ("source_snapshot", "dependency_keys"),
        ("operation", "discovery_evidence"),
        ("assets",),
        ("quality_rows",),
        ("references",),
        ("duplicates", "candidates"),
    )
    import random

    rng = random.Random(3249)
    for _ in range(8):
        trial = copy.deepcopy(unsigned)
        for path in paths:
            target = trial
            for key in path[:-1]:
                target = target[key]  # type: ignore[index]
            items = list(target[path[-1]])  # type: ignore[index]
            rng.shuffle(items)
            target[path[-1]] = items  # type: ignore[index]
        _refresh(trial)
        result = validate_artifact_manifest(trial)
        assert result.status is ValidationStatus.VALID, result.reason_codes
        assert result.record is not None
        assert result.record.fingerprint == expected
        again = validate_artifact_manifest(result.record.to_dict())
        assert again.status is ValidationStatus.VALID
        assert again.record is not None
        assert again.record.fingerprint == expected


def test_manifest_accepts_material_requirement_v2_reference() -> None:
    """Manifests can bind MaterialRequirement v2 records (which carry visual direction)."""
    value = _noncanonical_manifest()
    value["requirement_reference"]["contract_version"] = (  # type: ignore[index]
        "curriculum-material-requirement-v2"
    )
    _refresh(value)
    first, second = _manifest_round_trip(value)
    assert first.record is not None and second.record is not None
    assert (
        first.record.to_dict()["requirement_reference"]["contract_version"]
        == "curriculum-material-requirement-v2"
    )
    assert second.record.fingerprint == first.record.fingerprint


def test_material_requirement_version_ids_match_canonical_definition() -> None:
    """The manifest's local v2 copy must track material_requirement's canonical IDs."""
    import instructional_workflow_contracts.material_requirement as requirement_module

    assert (
        manifest_module.MATERIAL_CONTRACT_ID
        == requirement_module.V1_CONTRACT_ID
        == "curriculum-material-requirement-v1"
    )
    assert (
        manifest_module.MATERIAL_V2_CONTRACT_ID
        == requirement_module.V2_CONTRACT_ID
        == "curriculum-material-requirement-v2"
    )
    assert manifest_module.MATERIAL_CONTRACT_IDS == frozenset(
        {
            requirement_module.V1_CONTRACT_ID,
            requirement_module.V2_CONTRACT_ID,
        }
    )


def test_tampered_manifest_fails_closed() -> None:
    first, _ = _manifest_round_trip(_noncanonical_manifest())
    assert first.record is not None
    payload = first.record.to_dict()
    tampered = copy.deepcopy(payload)
    tampered["artifact"]["mime_type"] = "application/x-tampered"  # type: ignore[index]
    assert validate_artifact_manifest(tampered).reason_codes == (
        "artifact-incompatible-fingerprint",
    )
    corrupted = copy.deepcopy(payload)
    corrupted["identity"]["source_fingerprint"] = "f" * 64  # type: ignore[index]
    assert validate_artifact_manifest(corrupted).reason_codes == (
        "artifact-incompatible-fingerprint",
    )


def test_repeated_manifest_round_trips_remain_stable() -> None:
    first, _ = _manifest_round_trip(_noncanonical_manifest())
    assert first.record is not None
    expected = first.record.fingerprint
    payload = first.record.to_dict()
    for _ in range(3):
        result = validate_artifact_manifest(copy.deepcopy(payload))
        assert result.status is ValidationStatus.VALID
        assert result.record is not None
        assert result.record.fingerprint == expected
        payload = result.record.to_dict()


def test_compatibility_accepts_round_tripped_manifest_record() -> None:
    """Consumer revalidation (compatibility _manifest_record) accepts round-tripped records."""
    import instructional_workflow_contracts.visual_asset_compatibility as compatibility_module

    envelope = json.loads(
        (
            FIXTURES_3249 / "valid_visual_asset_compatibility_v2.json"
        ).read_text(encoding="utf-8")
    )
    manifest_result = validate_artifact_manifest(envelope["artifact_manifest"])
    assert manifest_result.status is ValidationStatus.VALID
    assert manifest_result.record is not None
    # Feed the round-tripped record through the consumer path, which revalidates
    # record.to_dict() inside _manifest_record.
    envelope["artifact_manifest"] = manifest_result.record.to_dict()
    result = compatibility_module.validate_visual_asset_compatibility_evidence(envelope)
    assert result.status is ValidationStatus.VALID, result.reason_codes


def test_noncanonical_manifest_fixture_round_trips() -> None:
    """The checked-in non-canonical fixture survives the producer round trip."""
    value = json.loads(
        (FIXTURES_3249 / "noncanonical_artifact_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    _refresh(value)
    first, second = _manifest_round_trip(value)
    assert first.record is not None
    payload = first.record.to_dict()
    # Order-insensitive lists are canonicalized.
    assert [item["asset_id"] for item in payload["assets"]] == [
        "asset-1",
        "asset-2",
        "asset-3",
    ]
    assert payload["artifact"]["observed_sections"] == [
        "directions",
        "exit-ticket",
        "practice",
    ]
    assert payload["source_snapshot"]["dependency_keys"] == [
        "material.requirement",
        "source.lesson",
        "source.unit",
    ]
    assert second.record is not None
    assert second.record.fingerprint == first.record.fingerprint
