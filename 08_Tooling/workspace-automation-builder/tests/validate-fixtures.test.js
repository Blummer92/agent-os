#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const {
  validateHandoff,
  validateDryRunReceipt,
  assertNoUnsafeMarkers
} = require('../lib/validate-handoff');

const root = path.resolve(__dirname, '..');
const fixturesDir = path.join(root, 'fixtures');

function readJson(relativePath) {
  return JSON.parse(fs.readFileSync(path.join(root, relativePath), 'utf8'));
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
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

const validHandoff = readJson('fixtures/sync-handoff.valid.json');
const invalidMissingTarget = readJson('fixtures/sync-handoff.invalid-missing-target.json');
const invalidMissingRange = readJson('fixtures/sync-handoff.invalid-missing-range.json');
const validReceipt = readJson('fixtures/dry-run-receipt.valid.json');
const invalidCountMismatch = readJson('fixtures/dry-run-receipt.invalid-count-mismatch.json');
const invalidTargetMismatch = readJson('fixtures/dry-run-receipt.invalid-target-mismatch.json');

validateHandoff(validHandoff);
validateDryRunReceipt(validReceipt, { expectedWriteTarget: 'staging' });
assert(validHandoff.row_scope.next_cursor === null, 'final batch may use next_cursor=null');
assert(validReceipt.skipped_records.some((record) => record.reason === 'missing_file_id' && record.file_id === null), 'missing file_id must be represented in skipped_records');
assertThrows(() => validateHandoff(invalidMissingTarget), 'missing required field: target');
assertThrows(() => validateHandoff(invalidMissingRange), 'missing required field: range_a1');
assertThrows(() => validateDryRunReceipt(invalidCountMismatch, { expectedWriteTarget: 'staging' }), 'sync_candidate_count must equal verified_count');
assertThrows(() => validateDryRunReceipt(invalidTargetMismatch, { expectedWriteTarget: 'visual_asset_library' }), 'receipt target cannot authorize a different write target');
fs.readdirSync(fixturesDir).filter((name) => name.endsWith('.json')).forEach((name) => assertNoUnsafeMarkers(readJson(`fixtures/${name}`), name));

console.log('Workspace Automation Builder fixture validation passed.');
