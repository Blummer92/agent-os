#!/usr/bin/env node
const path = require('path');
const { spawnSync } = require('child_process');

const root = path.resolve(__dirname, '..');
const cli = path.join(root, 'bin', 'validate-handoff.js');

function fixture(name) {
  return path.join(root, 'fixtures', name);
}

function runCli(filePath) {
  return spawnSync(process.execPath, [cli, filePath], { encoding: 'utf8' });
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function assertPasses(name) {
  const result = runCli(fixture(name));
  assert(result.status === 0, `${name} should pass. stderr: ${result.stderr}`);
  assert(result.stdout.includes('Workspace Automation Builder validation passed.'), `${name} should print success output`);
}

function assertFails(name, expectedText) {
  const result = runCli(fixture(name));
  assert(result.status !== 0, `${name} should fail`);
  assert(result.stderr.includes('Workspace Automation Builder validation failed:'), `${name} should print validation failure prefix`);
  assert(result.stderr.includes(expectedText), `${name} should include ${expectedText}. stderr: ${result.stderr}`);
}

assertPasses('sync-handoff.valid.json');
assertPasses('dry-run-receipt.valid.json');
assertFails('sync-handoff.invalid-missing-target.json', 'missing required field: target');
assertFails('sync-handoff.invalid-missing-range.json', 'missing required field: range_a1');
assertFails('dry-run-receipt.invalid-count-mismatch.json', 'sync_candidate_count must equal verified_count');
assertFails('dry-run-receipt.invalid-target-mismatch.json', 'target_database_id appears to belong to visual_asset_library, not staging');

console.log('Workspace Automation Builder CLI validation tests passed.');
