import assert from 'node:assert/strict';
import test from 'node:test';
import { access, writeFile } from 'node:fs/promises';

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
  assert.deepEqual(result.screenshots, []);
  assert.equal(result.evidence_persisted, false);
  assert.equal(result.side_effects_performed, false);
});

test('Canva host uses tmpfs, returns screenshot bytes, and deletes the workspace', async () => {
  let observed;
  const fakePng = Buffer.from('\x89PNG\r\n\x1a\nsynthetic');
  const captureResult = Object.freeze({
    status: 'valid',
    capture: Object.freeze({
      format_version: 'software-tutorial-capture-v1',
      capture_id: 'tutorial0-canva',
      source: Object.freeze({ recording_sha256: fingerprintRecording(rawRecording) }),
    }),
  });
  const result = await runHostCapture(input(), {
    username: 'agent-os-canva-capture',
    capturedAt: '2026-09-15T22:00:00Z',
    captureImpl: async (value) => {
      observed = value;
      await writeFile(`${value.screenshotDir}/000-before.png`, fakePng);
      await writeFile(`${value.screenshotDir}/000-after.png`, fakePng);
      return captureResult;
    },
  });
  assert.equal(observed.rawRecording, rawRecording);
  assert.deepEqual(observed.approvedOrigins, ['https://www.canva.com']);
  assert.equal(observed.captureId, 'tutorial0-canva');
  assert.equal(observed.userDataDir, '/var/lib/agent-os/canva-capture-home/.agent-os/browser-profiles/canva');
  assert.match(observed.screenshotDir, /^\/dev\/shm\/agent-os-software-tutorial-capture-[^/]+\/screenshots$/);
  assert.equal(observed.authenticationStatus, 'AUTH_READY');
  assert.equal(observed.headless, true);
  assert.deepEqual(observed.launchOptions, { executablePath: '/usr/bin/chromium' });
  assert.equal(observed.captureTargetStyle, false);
  assert.equal(result.capture_result, captureResult);
  assert.equal(result.evidence_persisted, false);
  assert.equal(result.side_effects_performed, true);
  assert.deepEqual(result.screenshots.map((item) => item.filename), ['000-after.png', '000-before.png']);
  assert.deepEqual(Buffer.from(result.screenshots[0].content_base64, 'base64'), fakePng);
  await assert.rejects(() => access(observed.screenshotDir));
});

test('tmpfs workspace is removed when capture throws', async () => {
  let screenshotDir;
  await assert.rejects(() => runHostCapture(input(), {
    username: 'agent-os-canva-capture',
    captureImpl: async (value) => {
      screenshotDir = value.screenshotDir;
      await writeFile(`${value.screenshotDir}/000-before.png`, Buffer.from('partial'));
      throw new Error('synthetic failure');
    },
  }), /synthetic failure/);
  await assert.rejects(() => access(screenshotDir));
});
