var HandoffService = (function() {
  const UNIT_ALIGNMENT_SIGNALS = [
    'unit alignment',
    'unit_alignment',
    'unit_throughline',
    'daily_must_have_evidence',
    'teacher_anchor',
    'learning_target',
    'checkpoint_evidence',
    'source_of_truth_priority'
  ];

  const LOCKED_STATUS_VALUES = [
    'locked',
    'final',
    'finalized',
    'approved',
    'prepared_for_upload',
    'ready_for_upload'
  ];

  const OPTIONAL_EXTENSION_TERMS = [
    'storyboard',
    '3-panel',
    'three-panel',
    'hero moment',
    'comic page',
    'villain design',
    'expanded villain',
    'opposing force concept'
  ];

  function buildHandoffText(records, duplicateGroups, summary) {
    const unitAlignment = buildUnitAlignmentHandoff_(records || []);
    const blockedRecords = (records || []).filter(function(record) { return record.blocked; });
    const exportEligible = (records || []).filter(function(record) { return record.computedExportEligible; });

    return [
      'Unit Alignment Handoff Preview',
      '',
      'Destination: Unit Alignment Coach',
      'Read-only status: ON',
      'Total records reviewed in current view: ' + safeCount_(summary && summary.totalRecords, records),
      'Unit Alignment candidate rows: ' + unitAlignment.candidate_count,
      'Ready for Unit Alignment dry run: ' + unitAlignment.ready_count,
      'Blocked from Unit Alignment handoff: ' + unitAlignment.blocked_count,
      'Needs routing review: ' + unitAlignment.routing_review_count,
      'Duplicate candidate groups: ' + (duplicateGroups || []).length,
      '',
      'Unit Alignment dry-run gate:',
      '- Run dryRunUnitAlignmentCoachBatch before any staging write.',
      '- Use DM_NOTION_SYNC_SCOPE=UNIT_ALIGNMENT_COACH_BATCH.',
      '- Keep DM_NOTION_SYNC_MODE=DRY_RUN until every candidate row is verified.',
      '- For write preflight only, require DM_UNIT_ALIGNMENT_STAGING_WRITE_APPROVED=YES_UNIT_ALIGNMENT_STAGING_ONLY.',
      '- Stop if synced_count does not equal verified_count.',
      '',
      'Unit Alignment blockers caught:',
      '- Missing file_id: ' + unitAlignment.missing_file_id_count,
      '- Not locked/finalized/prepared for upload: ' + unitAlignment.unlocked_count,
      '- Missing daily checkpoint evidence: ' + unitAlignment.missing_checkpoint_count,
      '- Optional extension drift in core path: ' + unitAlignment.optional_extension_drift_count,
      '- Duplicate structure risk: ' + unitAlignment.duplicate_structure_risk_count,
      '',
      'Source dashboard context:',
      '- Computed export eligible: ' + exportEligible.length,
      '- Blocked records: ' + blockedRecords.length,
      '',
      'Governance reminder:',
      '- This handoff preview does not approve sources.',
      '- This handoff preview does not write to Unit Alignment, DM Source Library, Notion, Drive, Sheets, dashboards, or curriculum readiness.',
      '- This handoff preview does not make Visual Asset Library writes.',
      '- Production/library writes remain blocked unless the explicit approval property exists and dry-run verification passed.'
    ].join('\n');
  }

  function buildUnitAlignmentHandoff_(records) {
    const candidates = records.filter(isUnitAlignmentCandidate_);
    const rowResults = candidates.map(validateUnitAlignmentHandoffRow_);
    return {
      candidate_count: candidates.length,
      ready_count: rowResults.filter(function(result) { return result.status === 'ready'; }).length,
      blocked_count: rowResults.filter(function(result) { return result.status === 'blocked'; }).length,
      routing_review_count: rowResults.filter(function(result) { return result.routing_review; }).length,
      missing_file_id_count: countFailure_(rowResults, 'missing file_id'),
      unlocked_count: countFailure_(rowResults, 'not locked/finalized/prepared for upload'),
      missing_checkpoint_count: countFailure_(rowResults, 'missing daily checkpoint evidence'),
      optional_extension_drift_count: countFailure_(rowResults, 'optional extension drift in core path'),
      duplicate_structure_risk_count: countFailure_(rowResults, 'duplicate structure risk'),
      rows: rowResults
    };
  }

  function validateUnitAlignmentHandoffRow_(record) {
    const raw = getRaw_(record);
    const failures = [];
    if (!(record.fileId || raw.file_id)) failures.push('missing file_id');
    if (!isLockedStatus_(raw.alignment_status || raw.status || raw.upload_status || raw.review_status)) {
      failures.push('not locked/finalized/prepared for upload');
    }
    if (!hasCheckpointEvidence_(raw)) failures.push('missing daily checkpoint evidence');
    if (hasOptionalExtensionDrift_(raw)) failures.push('optional extension drift in core path');
    if (hasDuplicateStructureRisk_(raw)) failures.push('duplicate structure risk');

    const routingReview = hasInstructionalMaterialsSignal_(raw) && !hasModelingSignal_(raw);
    return {
      source_row: record.rowNumber || raw.rowNumber || '',
      file_id: record.fileId || raw.file_id || '',
      unit_name: raw.unit_name || record.fileName || raw.file_name || '',
      status: failures.length ? 'blocked' : 'ready',
      routing_review: routingReview,
      failures: failures
    };
  }

  function isUnitAlignmentCandidate_(record) {
    const raw = getRaw_(record);
    const text = stringify_(raw) + ' ' + stringify_(record);
    return UNIT_ALIGNMENT_SIGNALS.some(function(signal) {
      return text.indexOf(signal) !== -1;
    });
  }

  function hasCheckpointEvidence_(raw) {
    return Boolean(String(
      raw.checkpoint_evidence ||
      raw.daily_checkpoint ||
      raw.daily_must_have_evidence ||
      raw.must_have_evidence ||
      ''
    ).trim());
  }

  function hasOptionalExtensionDrift_(raw) {
    const path = normalize_(raw.pathway || raw.core_pathway || raw.required_path || raw.deliverable_scope);
    if (path.indexOf('optional') !== -1) return false;
    const text = stringify_(raw);
    const requiresText = /(required|must|core|daily evidence|assessment|rubric|must-have)/i.test(text);
    return requiresText && OPTIONAL_EXTENSION_TERMS.some(function(term) {
      return text.indexOf(term) !== -1;
    });
  }

  function hasDuplicateStructureRisk_(raw) {
    const classification = normalize_(raw.upload_classification || raw.formatting_classification || raw.validation_classification);
    if (classification === 'duplicate_existing_section' || classification === 'duplicate_existing_structure') return true;
    const text = stringify_(raw);
    return text.indexOf('duplicate section') !== -1 || text.indexOf('duplicate structure') !== -1;
  }

  function hasInstructionalMaterialsSignal_(raw) {
    const text = stringify_(raw);
    return ['worksheet', 'slide', 'deck', 'student-facing', 'student facing', 'layout', 'icons', 'visual asset'].some(function(signal) {
      return text.indexOf(signal) !== -1;
    });
  }

  function hasModelingSignal_(raw) {
    const text = stringify_(raw);
    return ['teacher says', 'teacher shows', 'teacher models', 'think-aloud', 'think aloud', 'modeling', 'demonstrates'].some(function(signal) {
      return text.indexOf(signal) !== -1;
    });
  }

  function countFailure_(rowResults, failureName) {
    return rowResults.filter(function(result) {
      return result.failures.indexOf(failureName) !== -1;
    }).length;
  }

  function isLockedStatus_(value) {
    return LOCKED_STATUS_VALUES.indexOf(normalize_(value)) !== -1;
  }

  function getRaw_(record) {
    return record && record.rawData ? record.rawData : record || {};
  }

  function safeCount_(summaryTotal, records) {
    return typeof summaryTotal === 'number' ? summaryTotal : (records || []).length;
  }

  function stringify_(value) {
    return JSON.stringify(value || {}).toLowerCase();
  }

  function normalize_(value) {
    return String(value || '').toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  }

  return {
    buildHandoffText: buildHandoffText,
    __test__: {
      buildUnitAlignmentHandoff: buildUnitAlignmentHandoff_,
      validateUnitAlignmentHandoffRow: validateUnitAlignmentHandoffRow_
    }
  };
})();
