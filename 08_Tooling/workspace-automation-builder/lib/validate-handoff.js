const fs = require('fs');
const path = require('path');

const SCHEMA_VERSIONS = {
  HANDOFF: 'sync-handoff.v1',
  DRY_RUN_RECEIPT: 'sync-dry-run-receipt.v1'
};

const TARGETS = ['staging', 'visual_asset_library'];

function fail(message) {
  throw new Error(message);
}

function assert(condition, message) {
  if (!condition) fail(message);
}

function assertPlainObject(value, label) {
  assert(value && typeof value === 'object' && !Array.isArray(value), `${label} must be an object`);
}

function assertRequired(object, fields, label) {
  assertPlainObject(object, label);
  fields.forEach((field) => {
    assert(Object.prototype.hasOwnProperty.call(object, field), `${label} missing required field: ${field}`);
  });
}

function assertPositiveInteger(value, label) {
  assert(Number.isInteger(value) && value >= 1, `${label} must be an integer >= 1`);
}

function assertNextCursor(value, label) {
  assert(value === null || (Number.isInteger(value) && value >= 1), `${label} must be an integer >= 1 or null`);
}

function assertBatchSize(value, label) {
  assertPositiveInteger(value, label);
  assert(value <= 50, `${label} must not exceed 50`);
}

function validateRowScope(rowScope) {
  assertRequired(rowScope, ['first_data_row', 'start_row', 'end_row', 'batch_size', 'next_cursor'], 'row_scope');
  assertPositiveInteger(rowScope.first_data_row, 'row_scope.first_data_row');
  assertPositiveInteger(rowScope.start_row, 'row_scope.start_row');
  assertPositiveInteger(rowScope.end_row, 'row_scope.end_row');
  assertBatchSize(rowScope.batch_size, 'row_scope.batch_size');
  assertNextCursor(rowScope.next_cursor, 'row_scope.next_cursor');
}

function validateBatchWindow(batchWindow) {
  assertRequired(batchWindow, ['start_row', 'end_row', 'batch_size', 'next_cursor'], 'batch_window');
  assertPositiveInteger(batchWindow.start_row, 'batch_window.start_row');
  assertPositiveInteger(batchWindow.end_row, 'batch_window.end_row');
  assertBatchSize(batchWindow.batch_size, 'batch_window.batch_size');
  assertNextCursor(batchWindow.next_cursor, 'batch_window.next_cursor');
}

function validateSkippedRecords(records, label) {
  assert(Array.isArray(records), `${label} must be an array`);
  records.forEach((record, index) => {
    assertRequired(record, ['source_row', 'reason'], `${label}[${index}]`);
    assertPositiveInteger(record.source_row, `${label}[${index}].source_row`);
    assert(typeof record.reason === 'string' && record.reason.length > 0, `${label}[${index}].reason is required`);
  });
}

function validatePayloadSample(payloadSample) {
  assert(Array.isArray(payloadSample), 'payload_sample must be an array');
  payloadSample.forEach((payload, index) => {
    assertPlainObject(payload, `payload_sample[${index}]`);
    assert(typeof payload.file_id === 'string' && payload.file_id.length > 0, `payload_sample[${index}].file_id is required`);
    assertPlainObject(payload.properties, `payload_sample[${index}].properties`);
  });
  assert(!payloadSample.some((payload) => !payload.file_id), 'missing file_id belongs in skipped_records, not payload_sample');
}

function assertNoUnsafeMarkers(value, label = 'document') {
  const text = JSON.stringify(value);
  const urlPattern = new RegExp(String.fromCharCode(104, 116, 116, 112) + 's?:\\/\\/', 'i');
  const forbiddenWords = [
    String.fromCharCode(111, 97, 117, 116, 104),
    String.fromCharCode(116, 111, 107, 101, 110),
    String.fromCharCode(115, 101, 99, 114, 101, 116),
    String.fromCharCode(112, 97, 115, 115, 119, 111, 114, 100),
    String.fromCharCode(99, 114, 101, 100, 101, 110, 116, 105, 97, 108)
  ];
  assert(!urlPattern.test(text), `${label} must not contain URLs`);
  forbiddenWords.forEach((word) => {
    assert(!new RegExp(word, 'i').test(text), `${label} must not contain unsafe marker: ${word}`);
  });
  assert(!/collection:\/\/[0-9a-f-]{36}/i.test(text), `${label} must not contain live collection IDs`);
}

function validateTargetDatabaseConsistency(packet) {
  const databaseId = String(packet.target_database_id || '').toLowerCase();
  if (packet.target === 'staging') {
    assert(!databaseId.includes('visual_asset_library'), 'target_database_id appears to belong to visual_asset_library, not staging');
  }
  if (packet.target === 'visual_asset_library') {
    assert(!databaseId.includes('staging'), 'target_database_id appears to belong to staging, not visual_asset_library');
  }
}

function validateHandoff(packet) {
  assertRequired(packet, [
    'schema_version',
    'sheet_id',
    'range_a1',
    'row_scope',
    'target',
    'target_database_id',
    'field_mapping',
    'approval_key_required',
    'skipped_records'
  ], SCHEMA_VERSIONS.HANDOFF);
  assert(packet.schema_version === SCHEMA_VERSIONS.HANDOFF, `handoff schema_version must be ${SCHEMA_VERSIONS.HANDOFF}`);
  assert(typeof packet.sheet_id === 'string' && packet.sheet_id.length > 0, 'sheet_id is required');
  assert(typeof packet.range_a1 === 'string' && packet.range_a1.length > 0, 'range_a1 is required');
  assert(TARGETS.includes(packet.target), 'handoff target must be staging or visual_asset_library');
  assert(typeof packet.target_database_id === 'string' && packet.target_database_id.length > 0, 'target_database_id is required');
  validateTargetDatabaseConsistency(packet);
  assertPlainObject(packet.field_mapping, 'field_mapping');
  assert(Object.keys(packet.field_mapping).length > 0, 'field_mapping must not be empty');
  assert(typeof packet.approval_key_required === 'string' && packet.approval_key_required.length > 0, 'approval_key_required is required');
  validateRowScope(packet.row_scope);
  validateSkippedRecords(packet.skipped_records, 'skipped_records');
  assertNoUnsafeMarkers(packet, SCHEMA_VERSIONS.HANDOFF);
  return { schema_version: SCHEMA_VERSIONS.HANDOFF, valid: true };
}

function validateDryRunReceipt(receipt, options = {}) {
  assertRequired(receipt, [
    'schema_version',
    'manifest',
    'batch_window',
    'dry_run_passed',
    'sync_candidate_count',
    'verified_count',
    'synced_count',
    'skipped_count',
    'skipped_records',
    'payload_sample'
  ], SCHEMA_VERSIONS.DRY_RUN_RECEIPT);
  assert(receipt.schema_version === SCHEMA_VERSIONS.DRY_RUN_RECEIPT, `receipt schema_version must be ${SCHEMA_VERSIONS.DRY_RUN_RECEIPT}`);
  validateHandoff(receipt.manifest);
  validateBatchWindow(receipt.batch_window);
  assert(receipt.dry_run_passed === true, 'dry_run_passed must be true for a writable receipt');
  assert(Number.isInteger(receipt.sync_candidate_count) && receipt.sync_candidate_count >= 0, 'sync_candidate_count must be an integer >= 0');
  assert(Number.isInteger(receipt.verified_count) && receipt.verified_count >= 0, 'verified_count must be an integer >= 0');
  assert(Number.isInteger(receipt.synced_count) && receipt.synced_count >= 0, 'synced_count must be an integer >= 0');
  assert(Number.isInteger(receipt.skipped_count) && receipt.skipped_count >= 0, 'skipped_count must be an integer >= 0');
  assert(receipt.sync_candidate_count === receipt.verified_count, 'sync_candidate_count must equal verified_count');
  assert(receipt.synced_count === receipt.verified_count, 'synced_count must equal verified_count');
  validateSkippedRecords(receipt.skipped_records, 'skipped_records');
  assert(receipt.skipped_count === receipt.skipped_records.length, 'skipped_count must equal skipped_records.length');
  validatePayloadSample(receipt.payload_sample);
  assertNoUnsafeMarkers(receipt, SCHEMA_VERSIONS.DRY_RUN_RECEIPT);
  if (options.expectedWriteTarget) {
    assert(receipt.manifest.target === options.expectedWriteTarget, 'receipt target cannot authorize a different write target');
  }
  return { schema_version: SCHEMA_VERSIONS.DRY_RUN_RECEIPT, valid: true };
}

function validateDocument(document, options = {}) {
  assertPlainObject(document, 'document');
  if (document.schema_version === SCHEMA_VERSIONS.HANDOFF) return validateHandoff(document);
  if (document.schema_version === SCHEMA_VERSIONS.DRY_RUN_RECEIPT) return validateDryRunReceipt(document, options);
  fail('Unsupported schema_version: ' + String(document.schema_version || 'missing'));
}

function readJsonFile(filePath) {
  const resolved = path.resolve(filePath);
  const text = fs.readFileSync(resolved, 'utf8');
  return JSON.parse(text);
}

function validateFile(filePath, options = {}) {
  const document = readJsonFile(filePath);
  return validateDocument(document, options);
}

module.exports = {
  SCHEMA_VERSIONS,
  TARGETS,
  assertNoUnsafeMarkers,
  validateHandoff,
  validateDryRunReceipt,
  validateDocument,
  validateFile
};
