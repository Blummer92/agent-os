import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import {
  BROWSER_SESSION_REF,
  BROWSER_SESSION_REFS,
  CANVA_BROWSER_SESSION_REF,
  EXECUTION_SURFACE,
  LIVE_CAPTURE_REQUEST_VERSION,
  PRIVACY_MODE,
  runLiveCaptureRequest,
} from '../live_capture_request.mjs';

const rawRecording = JSON.stringify({
  title: 'synthetic tutorial capture',
  steps: [
    { type: 'navigate', url: 'https://new.express.adobe.com/your-stuff/files' },
    { type: 'click', selectors: [["[data-testid='folder-asset-card-digitalmedia']"]], offsetX: 23, offsetY: 12 },
  ],
});
const recordingSha = createHash('sha256').update(Buffer.from(rawRecording)).digest('hex');

function request(overrides = {}) {
  return {
    format_version: LIVE_CAPTURE_REQUEST_VERSION,
    capture_request_id: 'tutorial0-step2',
    target_url: 'https://new.express.adobe.com/your-stuff/files',
    allowed_origins: ['https://new.express.adobe.com'],
    recording_source: {
      kind: 'chrome-devtools-recorder',
      sha256: recordingSha,
      content_ref: 'recorder/tutorial0.2.json',
    },
    browser_session_ref: BROWSER_SESSION_REF,
    privacy_mode: PRIVACY_MODE,
    ...overrides,
  };
}

function governedRequest(browserSessionRef) {
  if (browserSessionRef === CANVA_BROWSER_SESSION_REF) {
    return request({
      target_url: 'https://www.canva.com/',
      allowed_origins: ['https://www.canva.com'],
      browser_session_ref: CANVA_BROWSER_SESSION_REF,
    });
  }
  return request({ browser_session_ref: browserSessionRef });
}

function capability(authentication_status = 'AUTH_READY', browser_session_ref = BROWSER_SESSION_REF) {
  return { browser_session_ref, authentication_status };
}

function successTransport(overrides = {}) {
  return {
    transport_status: 'succeeded',
    execution_surface: EXECUTION_SURFACE,
    side_effects_performed: true,
    capture_result: {
      status: 'valid',
      capture: {
        format_version: 'software-tutorial-capture-v1',
        capture_id: 'tutorial0-step2',
        source: { recording_sha256: recordingSha },
      },
    },
    ...overrides,
  };
}

async function run(options = {}) {
  let calls = 0;
  const invokeCapture = options.invokeCapture ?? (async () => successTransport());
  const browserSessionCapability = Object.hasOwn(options, 'browserSessionCapability')
    ? options.browserSessionCapability
    : capability();
  const result = await runLiveCaptureRequest({
    request: options.request ?? request(),
    rawRecording: options.rawRecording ?? rawRecording,
    browserSessionCapability,
    executionSurface: options.executionSurface ?? EXECUTION_SURFACE,
    invokeCapture: async (input) => { calls += 1; return invokeCapture(input); },
    idempotencyLookup: options.idempotencyLookup,
    idempotencyRecord: options.idempotencyRecord,
  });
  return { result, calls };
}

test('valid Adobe request remains backward compatible and returns bounded capture identity', async () => {
  let received;
  const { result, calls } = await run({ invokeCapture: async (input) => { received = input; return successTransport(); } });
  assert.equal(calls, 1);
  assert.equal(BROWSER_SESSION_REF, 'adobe-express-default');
  assert.equal(received.operation, 'captureFlow');
  assert.deepEqual(received.execution_surface, EXECUTION_SURFACE);
  assert.equal(received.browser_session_ref, BROWSER_SESSION_REF);
  assert.equal(received.recording_sha256, recordingSha);
  assert.equal(result.transport_status, 'succeeded');
  assert.equal(result.capture_status, 'valid');
  assert.deepEqual(result.capture_ref, { format_version: 'software-tutorial-capture-v1', capture_id: 'tutorial0-step2', recording_sha256: recordingSha });
  assert.equal('userDataDir' in received, false);
  assert.equal('password' in received, false);
  assert.equal('cookie' in received, false);
  assert.equal('token' in received, false);
});

test('Canva request admits only canva-default and delegates unchanged to existing captureFlow transport', async () => {
  let received;
  const canvaRequest = governedRequest(CANVA_BROWSER_SESSION_REF);
  const { result, calls } = await run({
    request: canvaRequest,
    browserSessionCapability: capability('AUTH_READY', CANVA_BROWSER_SESSION_REF),
    invokeCapture: async (input) => { received = input; return successTransport(); },
  });
  assert.deepEqual(BROWSER_SESSION_REFS, ['adobe-express-default', 'canva-default']);
  assert.equal(calls, 1);
  assert.equal(received.operation, 'captureFlow');
  assert.equal(received.browser_session_ref, 'canva-default');
  assert.equal(received.target_url, 'https://www.canva.com/');
  assert.deepEqual(received.approved_origins, ['https://www.canva.com']);
  assert.equal(result.capture_status, 'valid');
});

test('unknown session identity and mismatched session capability fail before invocation', async () => {
  const unknown = await run({ request: request({ browser_session_ref: 'arbitrary-browser' }) });
  assert.equal(unknown.calls, 0);
  assert.equal(unknown.result.reason_codes[0], 'request-invalid');

  const canvaRequest = governedRequest(CANVA_BROWSER_SESSION_REF);
  const mismatch = await run({ request: canvaRequest, browserSessionCapability: capability('AUTH_READY', BROWSER_SESSION_REF) });
  assert.equal(mismatch.calls, 0);
  assert.equal(mismatch.result.reason_codes[0], 'browser-session-capability-missing');
});

test('unknown request version and arbitrary execution fields fail before invocation', async () => {
  for (const badRequest of [
    request({ format_version: 'software-tutorial-capture-request-v2' }),
    { ...request(), command: 'curl https://example.com' },
    { ...request(), script: 'alert(1)' },
    { ...request(), profile_path: '/tmp/profile' },
    { ...request(), display: ':99' },
    { ...request(), port: 6082 },
    { ...request(), executable_path: '/usr/bin/chromium' },
    { ...request(), launch_args: ['--remote-debugging-port=9222'] },
    { ...request(), password: 'secret' },
    { ...request(), cookie: 'session=value' },
    { ...request(), token: 'secret' },
  ]) {
    const { result, calls } = await run({ request: badRequest });
    assert.equal(calls, 0);
    assert.equal(result.reason_codes[0], 'request-invalid');
  }
});

test('off-origin target fails before invocation', async () => {
  const { result, calls } = await run({ request: request({ target_url: 'https://example.com/' }) });
  assert.equal(calls, 0);
  assert.equal(result.reason_codes[0], 'request-invalid');
});

test('recording digest mismatch fails before invocation', async () => {
  const { result, calls } = await run({ rawRecording: `${rawRecording} ` });
  assert.equal(calls, 0);
  assert.equal(result.reason_codes[0], 'recording-digest-mismatch');
});

test('missing and non-ready browser session capability fail before replay for both governed sessions', async () => {
  for (const browserSessionRef of BROWSER_SESSION_REFS) {
    const governed = governedRequest(browserSessionRef);
    for (const value of [undefined, capability('AUTH_REQUIRED', browserSessionRef), capability('AUTH_EXPIRED', browserSessionRef), capability('AUTH_BLOCKED', browserSessionRef)]) {
      const { result, calls } = await run({ request: governed, browserSessionCapability: value });
      assert.equal(calls, 0);
      assert.equal(result.capture_status, 'blocked');
    }
  }
});

test('execution surface mismatch fails closed with no silent substitution', async () => {
  const { result, calls } = await run({ executionSurface: { ...EXECUTION_SURFACE, instance: 'other-host' } });
  assert.equal(calls, 0);
  assert.equal(result.reason_codes[0], 'execution-surface-mismatch');
});

test('transport success and capture failure remain distinct', async () => {
  const { result, calls } = await run({ invokeCapture: async () => successTransport({ capture_result: { status: 'blocked', capture: null } }) });
  assert.equal(calls, 1);
  assert.equal(result.transport_status, 'succeeded');
  assert.equal(result.capture_status, 'blocked');
  assert.equal(result.reason_codes[0], 'capture-failed');
});

test('duplicate logical request reuses exact prior receipt without a second capture', async () => {
  const prior = {
    format_version: 'software-tutorial-capture-request-result-v1',
    capture_request_id: 'tutorial0-step2',
    request_fingerprint: null,
    execution_surface: EXECUTION_SURFACE,
    transport_status: 'succeeded',
    capture_status: 'valid',
    capture_ref: { format_version: 'software-tutorial-capture-v1', capture_id: 'tutorial0-step2', recording_sha256: recordingSha },
    recording_sha256: recordingSha,
    authentication_status: 'AUTH_READY',
    privacy_state: PRIVACY_MODE,
    reason_codes: [],
    side_effects_performed: true,
  };
  let stored;
  const first = await runLiveCaptureRequest({
    request: request(),
    rawRecording,
    browserSessionCapability: capability(),
    invokeCapture: async () => successTransport(),
    idempotencyLookup: async () => null,
    idempotencyRecord: async (_id, receipt) => { stored = receipt; },
  });
  assert.equal(first.capture_status, 'valid');
  assert.ok(stored.request_fingerprint);
  prior.request_fingerprint = stored.request_fingerprint;
  let calls = 0;
  const second = await runLiveCaptureRequest({
    request: request(),
    rawRecording,
    browserSessionCapability: capability(),
    invokeCapture: async () => { calls += 1; return successTransport(); },
    idempotencyLookup: async () => prior,
  });
  assert.equal(calls, 0);
  assert.equal(second.transport_status, 'deduplicated');
  assert.equal(second.side_effects_performed, false);
  assert.deepEqual(second.capture_ref, prior.capture_ref);
});

test('conflicting duplicate request identity fails closed without invoking capture', async () => {
  const { result, calls } = await run({ idempotencyLookup: async () => ({ request_fingerprint: '0'.repeat(64) }) });
  assert.equal(calls, 0);
  assert.equal(result.reason_codes[0], 'request-identity-conflict');
});

test('result identity mismatch fails closed', async () => {
  const { result, calls } = await run({ invokeCapture: async () => successTransport({ capture_result: { status: 'valid', capture: { format_version: 'software-tutorial-capture-v1', capture_id: 'wrong', source: { recording_sha256: recordingSha } } } }) });
  assert.equal(calls, 1);
  assert.equal(result.reason_codes[0], 'result-identity-mismatch');
  assert.equal(result.capture_ref, null);
});

test('adapter output never serializes auth/profile material or readiness authority', async () => {
  const { result } = await run();
  const serialized = JSON.stringify(result).toLowerCase();
  for (const forbidden of ['password', 'cookie', 'token', 'profile_path', 'userdata', 'picture_perfect_ready', 'classroom_ready', 'publication_authorized']) {
    assert.equal(serialized.includes(forbidden), false);
  }
  assert.equal(result.privacy_state, 'sensitive-by-default');
});
