import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';

import {
  CANVA_BROWSER_SESSION_REF,
  EXECUTION_SURFACE,
  LIVE_CAPTURE_REQUEST_VERSION,
  PRIVACY_MODE,
  runLiveCaptureRequest,
} from '../live_capture_request.mjs';
import {
  fingerprintAction,
  fingerprintRecording,
} from '../safe_recording.mjs';

const step = { type: 'change', selectors: [['#file']], value: 'C:\\fakepath\\practice.pdf' };
const rawRecording = JSON.stringify({ title: 'Synthetic file input', steps: [step] });
const recordingSha = fingerprintRecording(rawRecording);

function request() {
  return {
    format_version: LIVE_CAPTURE_REQUEST_VERSION,
    capture_request_id: 'file-input-test',
    target_url: 'https://www.canva.com/',
    allowed_origins: ['https://www.canva.com'],
    recording_source: {
      kind: 'chrome-devtools-recorder',
      sha256: recordingSha,
      content_ref: 'recorder/file-input-test.json',
    },
    browser_session_ref: CANVA_BROWSER_SESSION_REF,
    privacy_mode: PRIVACY_MODE,
  };
}

const capability = Object.freeze({
  browser_session_ref: CANVA_BROWSER_SESSION_REF,
  authentication_status: 'AUTH_READY',
});

function artifact(bytes = Buffer.from('synthetic upload bytes')) {
  return {
    source_index: 0,
    source_fingerprint: fingerprintAction(step),
    content_ref: 'capture-inputs/practice.pdf',
    sha256: createHash('sha256').update(bytes).digest('hex'),
    filename: 'practice.pdf',
    content_base64: bytes.toString('base64'),
  };
}

function successTransport() {
  return {
    transport_status: 'succeeded',
    execution_surface: EXECUTION_SURFACE,
    capture_result: {
      status: 'valid',
      capture: {
        format_version: 'software-tutorial-capture-v1',
        capture_id: 'file-input-test',
        source: { recording_sha256: recordingSha },
      },
    },
    screenshots: [],
    evidence_persisted: false,
    side_effects_performed: true,
  };
}

test('file-input bytes are admitted only as bounded runtime evidence and passed to transport', async () => {
  let observed;
  const result = await runLiveCaptureRequest({
    request: request(),
    rawRecording,
    browserSessionCapability: capability,
    fileInputArtifacts: [artifact()],
    invokeCapture: async (payload) => {
      observed = payload;
      return successTransport();
    },
  });
  assert.equal(result.capture_status, 'valid');
  assert.equal(observed.file_input_artifacts.length, 1);
  assert.equal(observed.file_input_artifacts[0].source_fingerprint, fingerprintAction(step));
  assert.equal('path' in observed.file_input_artifacts[0], false);
});

test('missing or digest-mismatched file evidence blocks before transport', async () => {
  let calls = 0;
  const missing = await runLiveCaptureRequest({
    request: request(),
    rawRecording,
    browserSessionCapability: capability,
    fileInputArtifacts: [],
    invokeCapture: async () => { calls += 1; return successTransport(); },
  });
  assert.equal(missing.capture_status, 'blocked');
  assert.equal(missing.reason_codes[0], 'file-input-artifact-invalid');

  const bad = artifact();
  bad.sha256 = '0'.repeat(64);
  const mismatch = await runLiveCaptureRequest({
    request: request(),
    rawRecording,
    browserSessionCapability: capability,
    fileInputArtifacts: [bad],
    invokeCapture: async () => { calls += 1; return successTransport(); },
  });
  assert.equal(mismatch.capture_status, 'blocked');
  assert.equal(mismatch.reason_codes[0], 'file-input-artifact-invalid');
  assert.equal(calls, 0);
});

test('file identity participates in duplicate request identity', async () => {
  let stored;
  const first = await runLiveCaptureRequest({
    request: request(),
    rawRecording,
    browserSessionCapability: capability,
    fileInputArtifacts: [artifact(Buffer.from('version one'))],
    invokeCapture: async () => successTransport(),
    idempotencyLookup: async () => null,
    idempotencyRecord: async (_id, receipt) => { stored = receipt; },
  });
  assert.equal(first.capture_status, 'valid');
  assert.ok(stored.request_fingerprint);

  let calls = 0;
  const second = await runLiveCaptureRequest({
    request: request(),
    rawRecording,
    browserSessionCapability: capability,
    fileInputArtifacts: [artifact(Buffer.from('version two'))],
    invokeCapture: async () => { calls += 1; return successTransport(); },
    idempotencyLookup: async () => stored,
  });
  assert.equal(second.capture_status, 'blocked');
  assert.equal(second.reason_codes[0], 'request-identity-conflict');
  assert.equal(calls, 0);
});
