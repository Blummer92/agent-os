import assert from 'node:assert/strict';
import test from 'node:test';

import { runGceLiveCaptureRequest } from '../gce_live_capture_request.mjs';
import {
  CANVA_BROWSER_SESSION_REF,
  EXECUTION_SURFACE,
  LIVE_CAPTURE_REQUEST_VERSION,
  PRIVACY_MODE,
} from '../live_capture_request.mjs';
import { fingerprintRecording } from '../safe_recording.mjs';

const rawRecording = JSON.stringify({ title: 'Synthetic Canva', steps: [] });
const recordingSha = fingerprintRecording(rawRecording);

function request(overrides = {}) {
  return {
    format_version: LIVE_CAPTURE_REQUEST_VERSION,
    capture_request_id: 'tutorial0-canva',
    target_url: 'https://www.canva.com/',
    allowed_origins: ['https://www.canva.com'],
    recording_source: {
      kind: 'chrome-devtools-recorder',
      sha256: recordingSha,
      content_ref: 'recorder/tutorial0-canva.json',
    },
    browser_session_ref: CANVA_BROWSER_SESSION_REF,
    privacy_mode: PRIVACY_MODE,
    ...overrides,
  };
}

const capability = Object.freeze({
  browser_session_ref: CANVA_BROWSER_SESSION_REF,
  authentication_status: 'AUTH_READY',
});

test('bounded GCE bridge delegates exactly once after request/auth/digest validation', async () => {
  const calls = [];
  const capture = Object.freeze({
    format_version: 'software-tutorial-capture-v1',
    capture_id: 'tutorial0-canva',
    source: Object.freeze({ recording_sha256: recordingSha }),
  });
  const result = await runGceLiveCaptureRequest({
    request: request(),
    rawRecording,
    browserSessionCapability: capability,
    invokeCapture: async (payload) => {
      calls.push(payload);
      return {
        transport_status: 'succeeded',
        execution_surface: EXECUTION_SURFACE,
        capture_result: { status: 'valid', capture },
        side_effects_performed: true,
      };
    },
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].operation, 'captureFlow');
  assert.equal(calls[0].browser_session_ref, CANVA_BROWSER_SESSION_REF);
  assert.equal(calls[0].raw_recording, rawRecording);
  assert.equal(result.transport_status, 'succeeded');
  assert.equal(result.capture_status, 'valid');
  assert.equal(result.capture_ref.capture_id, 'tutorial0-canva');
});

test('invalid request or digest never reaches GCE transport', async () => {
  let calls = 0;
  const invokeCapture = async () => { calls += 1; throw new Error('must not run'); };
  const invalid = await runGceLiveCaptureRequest({
    request: request({ target_url: 'https://example.com/' }),
    rawRecording,
    browserSessionCapability: capability,
    invokeCapture,
  });
  assert.equal(invalid.capture_status, 'blocked');

  const mismatch = await runGceLiveCaptureRequest({
    request: request(),
    rawRecording: `${rawRecording} `,
    browserSessionCapability: capability,
    invokeCapture,
  });
  assert.equal(mismatch.capture_status, 'blocked');
  assert.equal(calls, 0);
});

test('non-ready Canva capability never reaches GCE transport', async () => {
  let calls = 0;
  const result = await runGceLiveCaptureRequest({
    request: request(),
    rawRecording,
    browserSessionCapability: { ...capability, authentication_status: 'AUTH_REQUIRED' },
    invokeCapture: async () => { calls += 1; },
  });
  assert.equal(result.capture_status, 'blocked');
  assert.equal(calls, 0);
});
