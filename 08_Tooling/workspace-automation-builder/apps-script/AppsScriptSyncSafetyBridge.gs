/** Workspace automation sync safety helpers. No live Workspace calls. */
var SyncSafetyBridge = (function () {
  var TARGETS = { STAGING: 'staging', VISUAL_ASSET_LIBRARY: 'visual_asset_library' };
  var APPROVAL_KEYS = { STAGING: 'SYNC_APPROVED_STAGING', VISUAL_ASSET_LIBRARY: 'SYNC_APPROVED_VISUAL_ASSET_LIBRARY' };

  function failUnless(condition, message) { if (!condition) throw new Error(message); }
  function asNumber(value, label) { var n = Number(value); failUnless(!isNaN(n), label + ' must be numeric'); return n; }
  function nowIso_() { return new Date().toISOString(); }

  function normalizeTarget(target) {
    var value = String(target || '').trim().toLowerCase();
    if (value === 'library' || value === 'visual asset library') return TARGETS.VISUAL_ASSET_LIBRARY;
    if (value === TARGETS.STAGING || value === TARGETS.VISUAL_ASSET_LIBRARY) return value;
    throw new Error('Unknown target: ' + target);
  }

  function selectTargetDatabase(config) {
    failUnless(config, 'config is required');
    var target = normalizeTarget(config.target);
    if (target === TARGETS.STAGING) {
      failUnless(config.stagingDatabaseId, 'stagingDatabaseId is required');
      return { target: target, databaseId: config.stagingDatabaseId, approvalKey: APPROVAL_KEYS.STAGING };
    }
    failUnless(config.visualAssetLibraryDatabaseId, 'visualAssetLibraryDatabaseId is required');
    return { target: target, databaseId: config.visualAssetLibraryDatabaseId, approvalKey: APPROVAL_KEYS.VISUAL_ASSET_LIBRARY };
  }

  function calculateBatchWindow(options) {
    failUnless(options, 'options are required');
    var firstDataRow = asNumber(options.firstDataRow || 2, 'firstDataRow');
    var startRow = Math.max(firstDataRow, asNumber(options.startRow || firstDataRow, 'startRow'));
    var maxRow = asNumber(options.maxRow, 'maxRow');
    var batchSize = asNumber(options.batchSize, 'batchSize');
    failUnless(batchSize > 0, 'batchSize must be greater than zero');
    failUnless(maxRow >= firstDataRow, 'maxRow must be at least firstDataRow');
    var endRow = Math.min(maxRow, startRow + batchSize - 1);
    var nextCursor = endRow >= maxRow ? null : endRow + 1;
    return { firstDataRow: firstDataRow, startRow: startRow, endRow: endRow, batchSize: batchSize, rowCount: endRow - startRow + 1, nextCursor: nextCursor, isFinalBatch: nextCursor === null };
  }

  function assertRowScope(rowNumber, scope) {
    failUnless(scope, 'scope is required');
    var row = asNumber(rowNumber, 'rowNumber');
    var startRow = asNumber(scope.startRow, 'scope.startRow');
    var endRow = asNumber(scope.endRow, 'scope.endRow');
    failUnless(row >= startRow && row <= endRow, 'Row ' + row + ' is outside approved scope ' + startRow + '-' + endRow);
    return true;
  }

  function mapDriveFileToNotionPayload(row, mapping) {
    failUnless(row, 'row is required');
    failUnless(mapping, 'mapping is required');
    var fileIdKey = mapping.file_id || 'file_id';
    var fileId = row[fileIdKey];
    if (!fileId) return { skipped: true, skip_reason: 'missing_file_id', source_row: row.__row_number || row.row_number || null };
    var properties = {};
    Object.keys(mapping).forEach(function (notionField) {
      if (notionField === 'file_id') return;
      var sourceKey = mapping[notionField];
      properties[notionField] = row[sourceKey] == null ? '' : row[sourceKey];
    });
    properties.file_id = fileId;
    return { skipped: false, source_row: row.__row_number || row.row_number || null, file_id: fileId, properties: properties };
  }

  function buildDriveManifest(input) {
    failUnless(input, 'input is required');
    failUnless(input.agentName, 'agentName is required');
    failUnless(input.sheetId, 'sheetId is required');
    failUnless(input.rangeA1, 'rangeA1 is required');
    var targetSelection = selectTargetDatabase(input);
    return { schema_version: 'sync-handoff.v1', created_at: nowIso_(), created_by_agent: input.agentName, sheet_id: input.sheetId, range_a1: input.rangeA1, target: targetSelection.target, target_database_id: targetSelection.databaseId, approval_key_required: targetSelection.approvalKey, expected_columns: input.expectedColumns || [], row_scope: input.rowScope || null, notes: input.notes || '' };
  }

  function createDryRunReceipt(input) {
    failUnless(input, 'input is required');
    failUnless(input.manifest, 'manifest is required');
    failUnless(input.batchWindow, 'batchWindow is required');
    var payloads = input.payloads || [];
    var skipped = input.skippedRecords || [];
    var verifiedCount = asNumber(input.verifiedCount || 0, 'verifiedCount');
    var syncCandidateCount = payloads.filter(function (payload) { return !payload.skipped; }).length;
    return { schema_version: 'sync-dry-run-receipt.v1', created_at: nowIso_(), manifest: input.manifest, batch_window: input.batchWindow, dry_run_passed: Boolean(input.dryRunPassed), sync_candidate_count: syncCandidateCount, verified_count: verifiedCount, synced_count: asNumber(input.syncedCount || 0, 'syncedCount'), skipped_count: skipped.length, skipped_records: skipped, payload_sample: payloads.slice(0, input.sampleSize || 5), verification_notes: input.verificationNotes || '' };
  }

  function assertDryRunPassed(receipt) {
    failUnless(receipt, 'dry-run receipt is required');
    failUnless(receipt.dry_run_passed === true, 'Write blocked: dry run has not passed');
    failUnless(receipt.sync_candidate_count === receipt.verified_count, 'Write blocked: sync_candidate_count must equal verified_count');
    return true;
  }

  function assertExplicitApproval(target, properties) {
    var normalizedTarget = normalizeTarget(target);
    var approvalKey = normalizedTarget === TARGETS.VISUAL_ASSET_LIBRARY ? APPROVAL_KEYS.VISUAL_ASSET_LIBRARY : APPROVAL_KEYS.STAGING;
    var props = properties || PropertiesService.getScriptProperties();
    var value = props.getProperty ? props.getProperty(approvalKey) : props[approvalKey];
    failUnless(value === 'true', 'Write blocked: missing explicit approval property ' + approvalKey + '=true');
    return true;
  }

  function assertVerifiedSyncCounts(result) {
    failUnless(result, 'sync result is required');
    var syncedCount = asNumber(result.synced_count, 'synced_count');
    var verifiedCount = asNumber(result.verified_count, 'verified_count');
    failUnless(syncedCount === verifiedCount, 'Write blocked: synced_count ' + syncedCount + ' does not equal verified_count ' + verifiedCount);
    return true;
  }

  function assertWriteAllowed(options) {
    failUnless(options, 'options are required');
    var receipt = options.dryRunReceipt;
    assertDryRunPassed(receipt);
    failUnless(receipt.manifest, 'Write blocked: dry-run receipt manifest is required');
    failUnless(receipt.manifest.target, 'Write blocked: dry-run receipt target is required');
    failUnless(receipt.manifest.target_database_id, 'Write blocked: dry-run receipt target_database_id is required');
    var target = normalizeTarget(options.target || receipt.manifest.target);
    failUnless(normalizeTarget(receipt.manifest.target) === target, 'Write blocked: dry-run receipt target does not match requested target');
    var expectedTargetDatabaseId = options.expectedTargetDatabaseId || (options.targetSelection && options.targetSelection.databaseId);
    failUnless(expectedTargetDatabaseId, 'Write blocked: expected target database id is required');
    failUnless(receipt.manifest.target_database_id === expectedTargetDatabaseId, 'Write blocked: target database does not match expected target');
    assertExplicitApproval(target, options.properties);
    assertVerifiedSyncCounts({ synced_count: receipt.synced_count, verified_count: receipt.verified_count });
    return true;
  }

  function runSelfTests() {
    var props = { SYNC_APPROVED_STAGING: 'true', getProperty: function (key) { return this[key]; } };
    var win = calculateBatchWindow({ startRow: 2, maxRow: 51, batchSize: 25 });
    failUnless(win.endRow === 26 && win.nextCursor === 27, '25-row cursor math failed');
    var manifest = buildDriveManifest({ agentName: 'Google Workspace Automation Engineer', sheetId: 'sheet_fixture', rangeA1: 'Assets!A2:H26', target: 'staging', stagingDatabaseId: 'db_staging', visualAssetLibraryDatabaseId: 'db_library' });
    var receipt = createDryRunReceipt({ manifest: manifest, batchWindow: win, dryRunPassed: true, payloads: [{ skipped: false, file_id: 'file_1' }], verifiedCount: 1, syncedCount: 1 });
    assertWriteAllowed({ dryRunReceipt: receipt, target: 'staging', expectedTargetDatabaseId: 'db_staging', properties: props });
    return 'All SyncSafetyBridge self-tests passed';
  }

  return { TARGETS: TARGETS, APPROVAL_KEYS: APPROVAL_KEYS, normalizeTarget: normalizeTarget, selectTargetDatabase: selectTargetDatabase, calculateBatchWindow: calculateBatchWindow, assertRowScope: assertRowScope, mapDriveFileToNotionPayload: mapDriveFileToNotionPayload, buildDriveManifest: buildDriveManifest, createDryRunReceipt: createDryRunReceipt, assertDryRunPassed: assertDryRunPassed, assertExplicitApproval: assertExplicitApproval, assertVerifiedSyncCounts: assertVerifiedSyncCounts, assertWriteAllowed: assertWriteAllowed, runSelfTests: runSelfTests };
})();
