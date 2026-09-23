/**
 * Dedicated offline tests for AppsScriptSyncSafetyBridge.gs.
 * These tests use local fixtures only and do not call Workspace services.
 */
function runAppsScriptSyncSafetyBridgeTests() {
  var tests = [
    testRows2To11Batch_,
    testTwentyFiveRowBatch_,
    testFiftyRowCursorProgression_,
    testFinalCursorBatch_,
    testRowScopeRejectsOutsideRange_,
    testMissingFileIdSkipsWithoutPayload_,
    testPayloadMappingUsesIntendedColumns_,
    testDryRunMissingOrFalseBlocksWrite_,
    testMissingApprovalBlocksWrite_,
    testStagingApprovalCannotAuthorizeLibraryWrite_,
    testWrongTargetDatabaseBlocksWrite_,
    testCandidateVerifiedMismatchBlocksWrite_,
    testSyncedVerifiedMismatchBlocksWrite_,
    testMissingManifestBlocksWrite_,
    testStagingReceiptCannotAuthorizeLibraryWrite_,
    testValidReceiptPassesWriteReview_,
    testTargetSpecificApprovalPassesOnlyForTarget_
  ];
  var results = tests.map(function(testFn) {
    try {
      testFn();
      return { name: testFn.name, status: 'passed' };
    } catch (error) {
      return { name: testFn.name, status: 'failed', message: error.message };
    }
  });
  var failures = results.filter(function(result) { return result.status === 'failed'; });
  if (failures.length) throw new Error('SyncSafetyBridge tests failed: ' + JSON.stringify(results));
  if (typeof Logger !== 'undefined') Logger.log(JSON.stringify(results, null, 2));
  return results;
}

function testRows2To11Batch_() {
  var win = SyncSafetyBridge.calculateBatchWindow({ firstDataRow: 2, startRow: 2, maxRow: 11, batchSize: 10 });
  assertEquals_(2, win.startRow, 'start row');
  assertEquals_(11, win.endRow, 'end row');
  assertEquals_(null, win.nextCursor, 'final cursor');
}

function testTwentyFiveRowBatch_() {
  var win = SyncSafetyBridge.calculateBatchWindow({ startRow: 2, maxRow: 51, batchSize: 25 });
  assertEquals_(26, win.endRow, '25-row end row');
  assertEquals_(27, win.nextCursor, '25-row next cursor');
}

function testFiftyRowCursorProgression_() {
  var first = SyncSafetyBridge.calculateBatchWindow({ startRow: 2, maxRow: 101, batchSize: 50 });
  var second = SyncSafetyBridge.calculateBatchWindow({ startRow: first.nextCursor, maxRow: 101, batchSize: 50 });
  assertEquals_(51, first.endRow, 'first batch end');
  assertEquals_(52, second.startRow, 'second starts at first unprocessed row');
  assertEquals_(101, second.endRow, 'second batch end');
  assertEquals_(null, second.nextCursor, 'no repeated or skipped row');
}

function testFinalCursorBatch_() {
  var win = SyncSafetyBridge.calculateBatchWindow({ startRow: 52, maxRow: 61, batchSize: 25 });
  assertEquals_(null, win.nextCursor, 'final next cursor');
  assertEquals_(10, win.rowCount, 'all final rows accounted for');
}

function testRowScopeRejectsOutsideRange_() {
  assertThrows_(function() {
    SyncSafetyBridge.assertRowScope(12, { startRow: 2, endRow: 11 });
  }, 'outside approved scope');
}

function testMissingFileIdSkipsWithoutPayload_() {
  var payload = SyncSafetyBridge.mapDriveFileToNotionPayload({ __row_number: 4, title: 'No file id' }, { file_id: 'file_id', Name: 'title' });
  assertEquals_(true, payload.skipped, 'missing file_id skipped');
  assertEquals_('missing_file_id', payload.skip_reason, 'skip reason');
  assertEquals_(undefined, payload.properties, 'no partial payload properties');
}

function testPayloadMappingUsesIntendedColumns_() {
  var payload = SyncSafetyBridge.mapDriveFileToNotionPayload({ file_id: 'file-1', title_col: 'Title', unit_col: 'Unit' }, { file_id: 'file_id', Name: 'title_col', Unit: 'unit_col' });
  assertEquals_(false, payload.skipped, 'payload created');
  assertEquals_('Title', payload.properties.Name, 'Name mapping');
  assertEquals_('Unit', payload.properties.Unit, 'Unit mapping');
}

function testDryRunMissingOrFalseBlocksWrite_() {
  assertThrows_(function() { SyncSafetyBridge.assertWriteAllowed(validWriteOptions_({ dryRunPassed: false })); }, 'dry run has not passed');
  assertThrows_(function() { SyncSafetyBridge.assertWriteAllowed({}); }, 'dry-run receipt is required');
}

function testMissingApprovalBlocksWrite_() {
  assertThrows_(function() { SyncSafetyBridge.assertWriteAllowed(validWriteOptions_({ properties: props_({}) })); }, 'missing explicit approval property');
}

function testStagingApprovalCannotAuthorizeLibraryWrite_() {
  assertThrows_(function() {
    SyncSafetyBridge.assertWriteAllowed(validWriteOptions_({ target: 'visual_asset_library', expectedTargetDatabaseId: 'db_library', properties: props_({ SYNC_APPROVED_STAGING: 'true' }) }));
  }, 'dry-run receipt target does not match requested target');
}

function testWrongTargetDatabaseBlocksWrite_() {
  assertThrows_(function() { SyncSafetyBridge.assertWriteAllowed(validWriteOptions_({ expectedTargetDatabaseId: 'db_wrong' })); }, 'target database does not match expected target');
}

function testCandidateVerifiedMismatchBlocksWrite_() {
  assertThrows_(function() { SyncSafetyBridge.assertWriteAllowed(validWriteOptions_({ verifiedCount: 2 })); }, 'sync_candidate_count must equal verified_count');
}

function testSyncedVerifiedMismatchBlocksWrite_() {
  assertThrows_(function() { SyncSafetyBridge.assertWriteAllowed(validWriteOptions_({ syncedCount: 0 })); }, 'synced_count 0 does not equal verified_count 1');
}

function testMissingManifestBlocksWrite_() {
  var opts = validWriteOptions_();
  delete opts.dryRunReceipt.manifest;
  assertThrows_(function() { SyncSafetyBridge.assertWriteAllowed(opts); }, 'manifest is required');
}

function testStagingReceiptCannotAuthorizeLibraryWrite_() {
  assertThrows_(function() {
    SyncSafetyBridge.assertWriteAllowed(validWriteOptions_({ target: 'visual_asset_library', expectedTargetDatabaseId: 'db_library', properties: props_({ SYNC_APPROVED_VISUAL_ASSET_LIBRARY: 'true' }) }));
  }, 'dry-run receipt target does not match requested target');
}

function testValidReceiptPassesWriteReview_() {
  assertEquals_(true, SyncSafetyBridge.assertWriteAllowed(validWriteOptions_()), 'valid receipt passes');
}

function testTargetSpecificApprovalPassesOnlyForTarget_() {
  var opts = validWriteOptions_({ properties: props_({ SYNC_APPROVED_STAGING: 'true', SYNC_APPROVED_VISUAL_ASSET_LIBRARY: 'false' }) });
  assertEquals_(true, SyncSafetyBridge.assertWriteAllowed(opts), 'staging approval passes staging only');
}

function validWriteOptions_(overrides) {
  overrides = overrides || {};
  var manifest = SyncSafetyBridge.buildDriveManifest({
    agentName: 'Google Workspace Automation Engineer',
    sheetId: 'sheet_fixture',
    rangeA1: 'Assets!A2:H26',
    target: 'staging',
    stagingDatabaseId: 'db_staging',
    visualAssetLibraryDatabaseId: 'db_library',
    rowScope: { firstDataRow: 2, startRow: 2, endRow: 26, batchSize: 25, nextCursor: 27 }
  });
  var receipt = SyncSafetyBridge.createDryRunReceipt({
    manifest: manifest,
    batchWindow: SyncSafetyBridge.calculateBatchWindow({ startRow: 2, maxRow: 26, batchSize: 25 }),
    dryRunPassed: overrides.hasOwnProperty('dryRunPassed') ? overrides.dryRunPassed : true,
    payloads: [{ skipped: false, file_id: 'file-1' }],
    skippedRecords: [],
    verifiedCount: overrides.hasOwnProperty('verifiedCount') ? overrides.verifiedCount : 1,
    syncedCount: overrides.hasOwnProperty('syncedCount') ? overrides.syncedCount : 1
  });
  return {
    dryRunReceipt: receipt,
    target: overrides.target || 'staging',
    expectedTargetDatabaseId: overrides.expectedTargetDatabaseId || 'db_staging',
    properties: overrides.properties || props_({ SYNC_APPROVED_STAGING: 'true' })
  };
}

function props_(values) {
  values = values || {};
  return { getProperty: function(key) { return values[key]; } };
}

function assertThrows_(fn, expectedText) {
  try {
    fn();
  } catch (error) {
    if (String(error.message).indexOf(expectedText) === -1) throw new Error('Expected error to include ' + expectedText + ', got ' + error.message);
    return true;
  }
  throw new Error('Expected function to throw ' + expectedText);
}

function assertEquals_(expected, actual, message) {
  if (expected !== actual) throw new Error(message + '. Expected ' + expected + ', got ' + actual);
}
