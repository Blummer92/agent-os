import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import {
  AUTH_STATUSES,
  CAPTURE_FORMAT_VERSION,
  CAPTURE_FORMAT_VERSION_V2,
  CAPTURE_REASON_CODES,
  TARGET_STYLE_PROPERTY_ALLOWLIST,
  authenticationBlocker,
  buildCaptureEnvelope,
  buildTargetStyleEvidence,
  fingerprintAction,
  fingerprintRecording,
  parseComputedColorToRgba,
  sanitizeBackgroundImage,
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

test('parseComputedColorToRgba reads canonical getComputedStyle color forms only', () => {
  assert.deepEqual(parseComputedColorToRgba('rgb(255, 0, 128)'), [255, 0, 128, 1]);
  assert.deepEqual(parseComputedColorToRgba('rgba(10, 20, 30, 0.5)'), [10, 20, 30, 0.5]);
  assert.deepEqual(parseComputedColorToRgba('rgb(10 20 30 / 50%)'), [10, 20, 30, 0.5]);
  assert.deepEqual(parseComputedColorToRgba('transparent'), [0, 0, 0, 0]);
  assert.equal(parseComputedColorToRgba('red'), null);
  assert.equal(parseComputedColorToRgba('#ff0080'), null);
  assert.equal(parseComputedColorToRgba(null), null);
});

test('sanitizeBackgroundImage retains bounded gradients and blocks external resource identity', () => {
  assert.equal(sanitizeBackgroundImage('none'), 'none');
  assert.equal(
    sanitizeBackgroundImage('linear-gradient(to right, rgb(0, 0, 0), rgb(255, 255, 255))'),
    'linear-gradient(to right, rgb(0, 0, 0), rgb(255, 255, 255))',
  );
  assert.equal(sanitizeBackgroundImage('radial-gradient(circle, red, blue)'), 'radial-gradient(circle, red, blue)');
  assert.equal(sanitizeBackgroundImage('repeating-linear-gradient(45deg, red, blue 10px)'), 'repeating-linear-gradient(45deg, red, blue 10px)');
  assert.equal(sanitizeBackgroundImage('url("https://example.com/x.png")'), null);
  assert.equal(sanitizeBackgroundImage('url(blob:https://example.com/abc)'), null);
  assert.equal(sanitizeBackgroundImage('url(data:image/png;base64,AAAA)'), null);
  assert.equal(sanitizeBackgroundImage('linear-gradient(red, blue), url(https://example.com/x.png)'), null);
  assert.equal(sanitizeBackgroundImage('paint(worklet)'), null);
  assert.equal(sanitizeBackgroundImage(''), null);
  assert.equal(sanitizeBackgroundImage(null), null);
});

test('buildTargetStyleEvidence is deterministic and fabricates nothing for unavailable properties', () => {
  const rect = [0.1, 0.2, 0.3, 0.4];
  const evidence = buildTargetStyleEvidence(rect, {
    color: 'rgb(0, 0, 0)',
    backgroundColor: 'rgba(255, 255, 255, 0.5)',
    opacity: '1',
    fontFamily: 'Arial',
    fontSize: '16px',
    fontWeight: '700',
    fontStyle: 'normal',
    lineHeight: '24px',
    letterSpacing: 'normal',
    borderRadius: '4px',
    backgroundImage: 'linear-gradient(red, blue)',
    boxShadow: 'none',
    textShadow: 'none',
    transform: 'none',
  });
  assert.deepEqual(evidence.rect_normalized, rect);
  assert.deepEqual(evidence.color_rgba, [0, 0, 0, 1]);
  assert.deepEqual(evidence.background_rgba, [255, 255, 255, 0.5]);
  assert.equal(evidence.opacity, 1);
  assert.equal(evidence.font_size_px, 16);
  assert.equal(evidence.font_weight, 700);
  assert.equal(evidence.background_image, 'linear-gradient(red, blue)');

  const again = buildTargetStyleEvidence(rect, { color: 'rgb(0, 0, 0)' });
  assert.deepEqual(again, buildTargetStyleEvidence(rect, { color: 'rgb(0, 0, 0)' }));
  assert.equal(again.font_family, null);
  assert.equal(again.background_image, null);
  assert.equal(again.box_shadow, null);

  assert.throws(() => buildTargetStyleEvidence([0.1, 0.2, 0.3], {}), /rectNormalized/);
  assert.throws(() => buildTargetStyleEvidence([0.1, 0.2, 0.3, Number.NaN], {}), /rectNormalized/);
});

function styledActionEvidence() {
  return [
    {
      source_index: 0,
      source_fingerprint: fingerprintAction({ type: 'click', selectors: [['aria/Test']] }),
      target_geometry: { target_x: 1, target_y: 2, target_width: 3, target_height: 4 },
      target_style: buildTargetStyleEvidence([0.1, 0.1, 0.2, 0.2], { color: 'rgb(1, 2, 3)' }),
      screenshot_before: '000-before.png',
      screenshot_after: '000-after.png',
    },
  ];
}

test('capture v1 envelope shape is unaffected by target_style support existing', () => {
  const validation = { status: 'valid', recording_sha256: 'a'.repeat(64), actions: [] };
  const envelope = buildCaptureEnvelope({
    captureId: 'cap-1',
    capturedAt: '2026-08-29T00:00:00Z',
    validation,
    actionEvidence: styledActionEvidence(),
  });
  assert.equal(envelope.format_version, CAPTURE_FORMAT_VERSION);
  assert.equal(Object.prototype.hasOwnProperty.call(envelope.actions[0], 'target_style'), false);
});

test('capture v2 envelope accepts optional target style and v1/v2 coexist', () => {
  const validation = { status: 'valid', recording_sha256: 'a'.repeat(64), actions: [] };
  const actionEvidence = styledActionEvidence();
  const v1 = buildCaptureEnvelope({ captureId: 'cap-1', capturedAt: '2026-08-29T00:00:00Z', validation, actionEvidence });
  const v2 = buildCaptureEnvelope({
    captureId: 'cap-1',
    capturedAt: '2026-08-29T00:00:00Z',
    validation,
    actionEvidence,
    formatVersion: CAPTURE_FORMAT_VERSION_V2,
  });
  assert.equal(v2.format_version, CAPTURE_FORMAT_VERSION_V2);
  assert.deepEqual(v2.actions[0].target_style, actionEvidence[0].target_style);
  // Adding style evidence changes nothing about identity-bearing fields shared with v1.
  assert.equal(v2.source.recording_sha256, v1.source.recording_sha256);
  assert.equal(v2.actions[0].source_fingerprint, v1.actions[0].source_fingerprint);
  assert.deepEqual(v2.actions[0].target_geometry, v1.actions[0].target_geometry);
});

test('unknown capture format version fails closed', () => {
  const validation = { status: 'valid', recording_sha256: 'a'.repeat(64), actions: [] };
  assert.throws(
    () => buildCaptureEnvelope({ captureId: 'cap-1', capturedAt: '2026-08-29T00:00:00Z', validation, formatVersion: 'software-tutorial-capture-v3' }),
    /unsupported capture format version/,
  );
});

test('adding target_style leaves fingerprintAction and recording identity byte-identical', () => {
  const step = { type: 'click', selectors: [['aria/Test']], offsetX: 1, offsetY: 2 };
  const before = fingerprintAction(step);
  buildTargetStyleEvidence([0.1, 0.1, 0.2, 0.2], { color: 'rgb(1, 2, 3)', backgroundImage: 'url(https://x/y.png)' });
  assert.equal(fingerprintAction(step), before);
  assert.equal(fingerprintRecording(Buffer.from(JSON.stringify({ steps: [step] }))), fingerprintRecording(Buffer.from(JSON.stringify({ steps: [step] }))));
});

test('target-style allowlist stays frozen and finite', () => {
  assert.ok(Object.isFrozen(TARGET_STYLE_PROPERTY_ALLOWLIST));
  assert.ok(TARGET_STYLE_PROPERTY_ALLOWLIST.includes('backgroundImage'));
  assert.ok(!TARGET_STYLE_PROPERTY_ALLOWLIST.includes('content'));
});
