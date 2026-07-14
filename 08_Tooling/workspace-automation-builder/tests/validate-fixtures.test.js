#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const fixturesDir = path.join(root, 'fixtures');

function readJson(relativePath) {
  return JSON.parse(fs.readFileSync(path.join(root, relativePath), 'utf8'));
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function assertRequired(object, fields, label) {
  fields.forEach((field) => {
    assert(Object.prototype.hasOwnProperty.call(object, field), `${label} missing required field: ${field}`);
  });
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
  ], 'sync-handoff.v1');
  assert(packet.schema_version === 'sync-handoff.v1', 'handoff schema_version must be sync-handoff.v1');
  assert(['staging', 'visual_asset_library'].includes(packet.target), 'handoff target must be staging or visual_asset_library');
  assert(packet.target_database_id.length > 0, 'handoff target_database_id is required');
  assert(packet.range_a1.length > 0, 'handoff range_a1 is required');
  assertRequired(packet.row_scope, ['first_data_row', 'start_row', 'end_row', 'batch_size', 'next_cursor'], 'row_scope');
  assert(packet.row_scope.batch_size <= 50, 'batch_size must not exceed 50');
  assert(packet.row_scope.next_cursor === null || Number.isInteger(packet.row_scope.next_cursor), 'next_cursor must be integer or null');
  assert(Object.keys(packet.field_mapping).length > 0, 'field_mapping must not be empty');
  assert(Array.isArray(packet.skipped_records), 'skipped_records must be an array');
}

function validateDryRunReceipt(receipt, expectedWriteTarget) {
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
  ], 'sync-dry-run-receipt.v1');
  assert(receipt.schema_version === 'sync-dry-run-receipt.v1', 'receipt schema_version must be sync-dry-run-receipt.v1');
  validateHandoff(receipt.manifest);
  assertRequired(receipt.batch_window, ['start_row', 'end_row', 'batch_size', 'next_cursor'], 'batch_window');
  assert(receipt.dry_run_passed === true, 'dry_run_passed must be true for a writable receipt');
  assert(receipt.sync_candidate_count === receipt.verified_count, 'sync_candidate_count must equal verified_count');
  assert(receipt.synced_count === receipt.verified_count, 'synced_count must equal verified_count');
  assert(receipt.skipped_count === receipt.skipped_records.length, 'skipped_count must equal skipped_records.length');
  assert(Array.isArray(receipt.payload_sample), 'payload_sample must be an array');
  assert(!receipt.payload_sample.some((payload) => !payload.file_id), 'missing file_id belongs in skipped_records, not payload_sample');
  if (expectedWriteTarget) {
    assert(receipt.manifest.target === expectedWriteTarget, 'receipt target cannot authorize a different write target');
  }
}

function assertThrows(fn, expectedText) {
  try {
    fn();
  } catch (error) {
    assert(String(error.message).includes(expectedText), `expected error to include "${expectedText}", got "${error.message}"`);
    return;
  }
  throw new Error(`expected function to throw "${expectedText}"`);
}

function assertFixtureIdsAreSanitized(fixture) {
  const text = JSON.stringify(fixture);
  assert(!/https?:\/\//i.test(text), 'fixtures must not contain private or production URLs');
  assert(!/(secret|token|oauth|password|credential)/i.test(text), 'fixtures must not contain secrets or credential words');
  assert(!/collection:\/\/[0-9a-f-]{36}/i.test(text), 'fixtures must not contain live collection IDs');
}

const validHandoff = readJson('fixtures/sync-handoff.valid.json');
const invalidMissingTarget = readJson('fixtures/sync-handoff.invalid-missing-target.json');
const invalidMissingRange = readJson('fixtures/sync-handoff.invalid-missing-range.json');
const validReceipt = readJson('fixtures/dry-run-receipt.valid.json');
const invalidCountMismatch = readJson('fixtures/dry-run-receipt.invalid-count-mismatch.json');
const invalidTargetMismatch = readJson('fixtures/dry-run-receipt.invalid-target-mismatch.json');

validateHandoff(validHandoff);
validateDryRunReceipt(validReceipt, 'staging');
assert(validHandoff.row_scope.next_cursor === null, 'final batch may use next_cursor=null');
assert(validReceipt.skipped_records.some((record) => record.reason === 'missing_file_id' && record.file_id === null), 'missing file_id must be represented in skipped_records');
assertThrows(() => validateHandoff(invalidMissingTarget), 'missing required field: target');
assertThrows(() => validateHandoff(invalidMissingRange), 'missing required field: range_a1');
assertThrows(() => validateDryRunReceipt(invalidCountMismatch, 'staging'), 'sync_candidate_count must equal verified_count');
assertThrows(() => validateDryRunReceipt(invalidTargetMismatch, 'visual_asset_library'), 'receipt target cannot authorize a different write target');
fs.readdirSync(fixturesDir).filter((name) => name.endsWith('.json')).forEach((name) => assertFixtureIdsAreSanitized(readJson(`fixtures/${name}`)));

console.log('Workspace Automation Builder fixture validation passed.');
