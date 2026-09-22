import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { BROWSER_SESSION_ORIGINS, EXECUTION_SURFACE, LIVE_CAPTURE_REQUEST_VERSION, PRIVACY_MODE, SCHOOLOGY_BROWSER_SESSION_REF, runLiveCaptureRequest } from '../live_capture_request.mjs';

const rawRecording = JSON.stringify({ title: 'synthetic Schoology to Kami tutorial', steps: [{ type: 'navigate', url: 'https://dpscd.schoology.com/home' }] });
const recordingSha = createHash('sha256').update(Buffer.from(rawRecording)).digest('hex');

function request(overrides = {}) { return {
  format_version: LIVE_CAPTURE_REQUEST_VERSION, capture_request_id: 'schoology-kami-tutorial',
  target_url: 'https://dpscd.schoology.com/home', allowed_origins: ['https://dpscd.schoology.com', 'https://web.kamihq.com'],
  recording_source: { kind: 'chrome-devtools-recorder', sha256: recordingSha, content_ref: 'recorder/schoology-kami.json' },
  browser_session_ref: SCHOOLOGY_BROWSER_SESSION_REF, privacy_mode: PRIVACY_MODE, ...overrides,
}; }
function capability(status = 'AUTH_READY') { return { browser_session_ref: SCHOOLOGY_BROWSER_SESSION_REF, authentication_status: status }; }
function success() { return { transport_status: 'succeeded', execution_surface: EXECUTION_SURFACE, side_effects_performed: true, capture_result: { status: 'valid', capture: { format_version: 'software-tutorial-capture-v1', capture_id: 'schoology-kami-tutorial', source: { recording_sha256: recordingSha } } } }; }
async function run(req = request(), cap = capability()) { let calls = 0; let received; const result = await runLiveCaptureRequest({ request: req, rawRecording, browserSessionCapability: cap, invokeCapture: async (input) => { calls += 1; received = input; return success(); } }); return { result, calls, received }; }

test('Schoology session is bound to the exact Schoology and Kami origins', async () => {
  assert.deepEqual(BROWSER_SESSION_ORIGINS[SCHOOLOGY_BROWSER_SESSION_REF], ['https://dpscd.schoology.com', 'https://web.kamihq.com']);
  const { result, calls, received } = await run();
  assert.equal(calls, 1); assert.equal(result.capture_status, 'valid'); assert.equal(received.browser_session_ref, 'schoology-default');
});

test('Schoology session rejects alternate tenant and incomplete origin sets', async () => {
  for (const req of [
    request({ allowed_origins: ['https://dpscd.schoology.com'] }),
    request({ target_url: 'https://example.schoology.com/home', allowed_origins: ['https://example.schoology.com', 'https://web.kamihq.com'] }),
    request({ allowed_origins: ['https://dpscd.schoology.com', 'https://example.kamihq.com'] }),
  ]) { const { result, calls } = await run(req); assert.equal(calls, 0); assert.equal(result.reason_codes[0], 'request-invalid'); }
});

test('Schoology request keeps non-ready auth blocked', async () => {
  for (const status of ['AUTH_REQUIRED', 'AUTH_EXPIRED', 'AUTH_BLOCKED']) { const { result, calls } = await run(request(), capability(status)); assert.equal(calls, 0); assert.equal(result.capture_status, 'blocked'); }
});

test('Schoology request rejects arbitrary browser and credential fields', async () => {
  for (const [key, value] of [['profile_path','/tmp/profile'],['display',':100'],['port',6083],['command','id'],['password','secret'],['cookie','x'],['token','x']]) { const { result, calls } = await run({ ...request(), [key]: value }); assert.equal(calls, 0); assert.equal(result.reason_codes[0], 'request-invalid'); }
});
