import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import {
  BROWSER_SESSION_ORIGINS,
  CANVA_BROWSER_SESSION_REF,
  EXECUTION_SURFACE,
  LIVE_CAPTURE_REQUEST_VERSION,
  PRIVACY_MODE,
  runLiveCaptureRequest,
} from '../live_capture_request.mjs';

const rawRecording = JSON.stringify({
  title: 'synthetic canva tutorial',
  steps: [{ type: 'navigate', url: 'https://www.canva.com/' }],
});
const recordingSha = createHash('sha256').update(Buffer.from(rawRecording)).digest('hex');

function canvaRequest(overrides = {}) {
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

function capability(authentication_status = 'AUTH_READY') {
  return { browser_session_ref: CANVA_BROWSER_SESSION_REF, authentication_status };
}

function successTransport() {
  return {
    transport_status: 'succeeded',
    execution_surface: EXECUTION_SURFACE,
    side_effects_performed: true,
    capture_result: {
      status: 'valid',
      capture: {
        format_version: 'software-tutorial-capture-v1',
        capture_id: 'tutorial0-canva',
        source: { recording_sha256: recordingSha },
      },
    },
  };
}

async function run(request = canvaRequest(), browserSessionCapability = capability(), executionSurface = EXECUTION_SURFACE) {
  let calls = 0;
  let received = null;
  const result = await runLiveCaptureRequest({
    request,
    rawRecording,
    browserSessionCapability,
    executionSurface,
    invokeCapture: async (input) => {
      calls += 1;
      received = input;
      return successTransport();
    },
  });
  return { result, calls, received };
}

test('Canva session is bound to the exact governed Canva origin', async () => {
  assert.deepEqual(BROWSER_SESSION_ORIGINS[CANVA_BROWSER_SESSION_REF], ['https://www.canva.com']);
  const { result, calls, received } = await run();
  assert.equal(calls, 1);
  assert.equal(result.capture_status, 'valid');
  assert.equal(received.browser_session_ref, 'canva-default');
  assert.equal(received.target_url, 'https://www.canva.com/');
  assert.deepEqual(received.approved_origins, ['https://www.canva.com']);
});

test('Canva session rejects an arbitrary matching target/origin pair before transport', async () => {
  const { result, calls } = await run(canvaRequest({
    target_url: 'https://example.com/tutorial',
    allowed_origins: ['https://example.com'],
  }));
  assert.equal(calls, 0);
  assert.equal(result.reason_codes[0], 'request-invalid');
});

test('Canva request rejects Adobe session capability before transport', async () => {
  const { result, calls } = await run(canvaRequest(), {
    browser_session_ref: 'adobe-express-default',
    authentication_status: 'AUTH_READY',
  });
  assert.equal(calls, 0);
  assert.equal(result.reason_codes[0], 'browser-session-capability-missing');
});

test('Canva request keeps non-ready auth states blocked', async () => {
  for (const status of ['AUTH_REQUIRED', 'AUTH_EXPIRED', 'AUTH_BLOCKED']) {
    const { result, calls } = await run(canvaRequest(), capability(status));
    assert.equal(calls, 0);
    assert.equal(result.capture_status, 'blocked');
  }
});

test('Canva request cannot widen fixed execution surface', async () => {
  const { result, calls } = await run(
    canvaRequest(),
    capability(),
    { ...EXECUTION_SURFACE, instance: 'other-host' },
  );
  assert.equal(calls, 0);
  assert.equal(result.reason_codes[0], 'execution-surface-mismatch');
});

test('Canva request rejects arbitrary browser and credential fields', async () => {
  for (const field of [
    ['profile_path', '/tmp/profile'],
    ['display', ':99'],
    ['port', 6082],
    ['executable_path', '/usr/bin/chromium'],
    ['launch_args', ['--remote-debugging-port=9222']],
    ['command', 'echo nope'],
    ['script', 'alert(1)'],
    ['password', 'secret'],
    ['cookie', 'session=value'],
    ['token', 'secret'],
  ]) {
    const [key, value] = field;
    const { result, calls } = await run({ ...canvaRequest(), [key]: value });
    assert.equal(calls, 0);
    assert.equal(result.reason_codes[0], 'request-invalid');
  }
});
