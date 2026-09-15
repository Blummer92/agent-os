import assert from 'node:assert/strict';
import test from 'node:test';

import {
  CAPTURE_HOST_MAX_INPUT_BYTES,
  runHostCapture,
  validateHostCaptureInput,
} from '../live_capture_host.mjs';
import {
  CANVA_BROWSER_SESSION_REF,
  EXECUTION_SURFACE,
  PRIVACY_MODE,
} from '../live_capture_request.mjs';
import { fingerprintRecording } from '../safe_recording.mjs';

const rawRecording = JSON.stringify({ title: 'Synthetic Canva', steps: [] });

function input(overrides = {}) {
  return {
    operation: 'captureFlow',
    execution_surface: EXECUTION_SURFACE,
    capture_request_id: 'tutorial0-canva',
    target_url: 'https://www.canva.com/',
    approved_origins: ['https://www.canva.com'],
    recording_sha256: fingerprintRecording(rawRecording),
    recording_content_ref: 'recorder/tutorial0-canva.json',
    browser_session_ref: CANVA_BROWSER_SESSION_REF,
    authentication_status: 'AUTH_READY',
    privacy_mode: PRIVACY_MODE,
    raw_recording: rawRecording,
    ...overrides,
  };
}

test('host validates exact SHA again before Replay', () => {
  assert.equal(validateHostCaptureInput(input()).recording_sha256, fingerprintRecording(rawRecording));
  assert.throws(() => validateHostCaptureInput(input({ recording_sha256: '0'.repeat(64) })), /digest mismatch/);
});

test('host rejects arbitrary execution fields and oversized Recorder input', () => {
  assert.throws(() => validateHostCaptureInput({ ...input(), command: 'id' }), /unsupported/);
  assert.throws(() => validateHostCaptureInput({ ...input(), profile_path: '/tmp/nope' }), /unsupported/);
  const tooLarge = 'x'.repeat(CAPTURE_HOST_MAX_INPUT_BYTES + 1);
  assert.throws(() => validateHostCaptureInput(input({ raw_recording: tooLarge, recording_sha256: fingerprintRecording(tooLarge) })), /byte bound/);
});

test('host fails closed when the process is not the fixed Canva capture identity', async () => {
  let invoked = false;
  const result = await runHostCapture(input(), {
    username: 'unexpected-user',
    captureImpl: async () => { invoked = true; throw new Error('must not invoke'); },
  });
  assert.equal(invoked, false);
  assert.equal(result.transport_status, 'succeeded');
  assert.equal(result.capture_result.status, 'blocked');
  assert.equal(result.capture_result.failure.reason_code, 'browser-session-user-mismatch');
  assert.equal(result.side_effects_performed, false);
});

test('Canva host binding invokes existing captureFlow contract with fixed profile and Chromium', async () => {
  let observed;
  const captureResult = Object.freeze({ status: 'blocked', capture: null, failure: Object.freeze({ reason_code: 'synthetic-stop' }) });
  const result = await runHostCapture(input(), {
    username: 'agent-os-canva-capture',
    capturedAt: '2026-09-15T22:00:00Z',
    captureImpl: async (value) => { observed = value; return captureResult; },
  });
  assert.equal(observed.rawRecording, rawRecording);
  assert.deepEqual(observed.approvedOrigins, ['https://www.canva.com']);
  assert.equal(observed.captureId, 'tutorial0-canva');
  assert.equal(observed.userDataDir, '/var/lib/agent-os/canva-capture-home/.agent-os/browser-profiles/canva');
  assert.match(observed.screenshotDir, /^\/var\/lib\/agent-os\/canva-capture-home\/\.agent-os\/tutorial-captures\/tutorial0-canva$/);
  assert.equal(observed.authenticationStatus, 'AUTH_READY');
  assert.equal(observed.headless, true);
  assert.deepEqual(observed.launchOptions, { executablePath: '/usr/bin/chromium' });
  assert.equal(observed.captureTargetStyle, false);
  assert.equal(result.capture_result, captureResult);
  assert.equal(result.side_effects_performed, true);
});
