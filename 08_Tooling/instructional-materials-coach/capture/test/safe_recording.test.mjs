import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import {
  AUTH_STATUSES,
  CAPTURE_REASON_CODES,
  authenticationBlocker,
  fingerprintAction,
  fingerprintRecording,
  validateAuthenticationStatus,
  validateRecording,
} from '../safe_recording.mjs';

const APPROVED_ORIGINS = ['https://new.express.adobe.com'];
const fixtureUrl = new URL('./fixtures/basic-recording.json', import.meta.url);
const fixture = await readFile(fixtureUrl);

function parseFixture() { return JSON.parse(fixture.toString('utf8')); }
function validate(value, options = {}) {
  return validateRecording(JSON.stringify(value), { approvedOrigins: APPROVED_ORIGINS, ...options });
}

test('synthetic Recorder fixture passes bounded preflight', () => {
  const result = validateRecording(fixture, { approvedOrigins: APPROVED_ORIGINS });
  assert.equal(result.status, 'valid');
  assert.equal(result.actions.length, 5);
  assert.match(result.recording_sha256, /^[0-9a-f]{64}$/);
});

test('unsupported known step fails closed before replay', () => {
  const recording = parseFixture();
  recording.steps[2] = { type: 'waitForExpression', expression: 'true' };
  const result = validate(recording);
  assert.equal(result.status, 'invalid');
  assert.equal(result.findings[0].reason_code, 'artifact-step-unsupported');
});

test('unknown future step fails closed before replay', () => {
  const recording = parseFixture();
  recording.steps.push({ type: 'futureMagicStep', payload: { action: 'doSomething' } });
  const result = validate(recording);
  assert.equal(result.status, 'invalid');
  assert.equal(result.findings.at(-1).reason_code, 'artifact-step-unsupported');
});

test('navigation is restricted to exact approved origins', () => {
  const recording = parseFixture();
  recording.steps[1].url = 'https://example.com/not-approved';
  const result = validate(recording);
  assert.equal(result.status, 'blocked');
  assert.equal(result.findings[0].reason_code, 'artifact-recording-invalid');
});

test('raw recording fingerprint is byte-stable and whitespace-sensitive', () => {
  assert.equal(fingerprintRecording(fixture), fingerprintRecording(Buffer.from(fixture)));
  assert.notEqual(fingerprintRecording(fixture), fingerprintRecording(`${fixture.toString('utf8')}\n`));
});

test('action fingerprint is stable across object key order', () => {
  const a = { type: 'click', selectors: [['aria/Test']], offsetX: 1, offsetY: 2 };
  const b = { offsetY: 2, offsetX: 1, selectors: [['aria/Test']], type: 'click' };
  assert.equal(fingerprintAction(a), fingerprintAction(b));
});

test('validation does not mutate caller JSON value', () => {
  const recording = parseFixture();
  const before = structuredClone(recording);
  validate(recording);
  assert.deepEqual(recording, before);
});

test('sensitive field names require manual review', () => {
  const recording = parseFixture();
  recording.steps[3].password = 'synthetic-secret';
  const result = validate(recording);
  assert.equal(result.status, 'manual-review-required');
  assert.equal(result.findings[0].reason_code, 'asset-sensitive-content');
});

test('account email values require manual review', () => {
  const recording = parseFixture();
  recording.steps[3].value = 'teacher@example.edu';
  const result = validate(recording);
  assert.equal(result.status, 'manual-review-required');
  assert.equal(result.findings[0].reason_code, 'asset-sensitive-content');
});

test('Recorder selectorAttribute top-level field is accepted', () => {
  const recording = parseFixture();
  recording.selectorAttribute = 'data-testid';
  assert.equal(validate(recording).status, 'valid');
});

test('unknown top-level fields fail closed', () => {
  const recording = parseFixture();
  recording.extensionPayload = { actions: [] };
  const result = validate(recording);
  assert.equal(result.status, 'invalid');
  assert.equal(result.findings[0].reason_code, 'artifact-recording-unknown-field');
});

test('unknown action-bearing step fields fail closed', () => {
  const recording = parseFixture();
  recording.steps[2].extensionAction = { command: 'synthetic-action' };
  const result = validate(recording);
  assert.equal(result.status, 'invalid');
  assert.equal(result.findings[0].reason_code, 'artifact-recording-unknown-field');
  assert.equal(result.findings[0].source_index, 2);
});

test('all emitted reason codes belong to the finite contract', () => {
  const recording = parseFixture();
  recording.steps.push({ type: 'futureMagicStep' });
  for (const finding of validate(recording).findings) assert.ok(CAPTURE_REASON_CODES.includes(finding.reason_code));
});

test('authentication status vocabulary is exact and finite', () => {
  assert.deepEqual(AUTH_STATUSES, ['AUTH_READY', 'AUTH_REQUIRED', 'AUTH_EXPIRED', 'AUTH_BLOCKED']);
  for (const status of AUTH_STATUSES) assert.equal(validateAuthenticationStatus(status), status);
  assert.throws(() => validateAuthenticationStatus('AUTH_UNKNOWN'), /unsupported authentication status/);
});

test('authentication blockers map non-ready states to finite authority reasons', () => {
  assert.equal(authenticationBlocker('AUTH_READY'), null);
  assert.equal(authenticationBlocker('AUTH_REQUIRED'), 'authority-auth-required');
  assert.equal(authenticationBlocker('AUTH_EXPIRED'), 'authority-auth-expired');
  assert.equal(authenticationBlocker('AUTH_BLOCKED'), 'authority-auth-blocked');
});
