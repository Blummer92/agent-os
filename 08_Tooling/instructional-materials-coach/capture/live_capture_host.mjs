import { mkdir } from 'node:fs/promises';
import os from 'node:os';
import { resolve } from 'node:path';

import { captureFlow } from './replay_capture.mjs';
import {
  BROWSER_SESSION_REF,
  CANVA_BROWSER_SESSION_REF,
  EXECUTION_SURFACE,
  PRIVACY_MODE,
} from './live_capture_request.mjs';
import { fingerprintRecording } from './safe_recording.mjs';

export const CAPTURE_HOST_INPUT_VERSION = 'software-tutorial-capture-host-input-v1';
export const CAPTURE_HOST_MAX_INPUT_BYTES = 512 * 1024;

const HOST_INPUT_FIELDS = new Set([
  'operation',
  'execution_surface',
  'capture_request_id',
  'target_url',
  'approved_origins',
  'recording_sha256',
  'recording_content_ref',
  'browser_session_ref',
  'authentication_status',
  'privacy_mode',
  'raw_recording',
]);

const HOST_SESSION_CONFIG = Object.freeze({
  [BROWSER_SESSION_REF]: Object.freeze({
    username: 'agent-os-capture',
    home: '/var/lib/agent-os/capture-home',
    profile: '/var/lib/agent-os/capture-home/.agent-os/browser-profiles/adobe-express',
    captureRoot: '/var/lib/agent-os/capture-home/.agent-os/tutorial-captures',
  }),
  [CANVA_BROWSER_SESSION_REF]: Object.freeze({
    username: 'agent-os-canva-capture',
    home: '/var/lib/agent-os/canva-capture-home',
    profile: '/var/lib/agent-os/canva-capture-home/.agent-os/browser-profiles/canva',
    captureRoot: '/var/lib/agent-os/canva-capture-home/.agent-os/tutorial-captures',
  }),
});

function exactKeys(value, allowed, label) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new TypeError(`${label} must be an object`);
  for (const key of Object.keys(value)) if (!allowed.has(key)) throw new TypeError(`unsupported ${label} field: ${key}`);
}

function exactSurface(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && value.kind === EXECUTION_SURFACE.kind
    && value.project === EXECUTION_SURFACE.project
    && value.zone === EXECUTION_SURFACE.zone
    && value.instance === EXECUTION_SURFACE.instance
    && Object.keys(value).length === 4;
}

export function validateHostCaptureInput(value) {
  exactKeys(value, HOST_INPUT_FIELDS, 'capture host input');
  if (value.operation !== 'captureFlow') throw new TypeError('unsupported capture operation');
  if (!exactSurface(value.execution_surface)) throw new TypeError('execution surface mismatch');
  if (typeof value.capture_request_id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(value.capture_request_id)) throw new TypeError('invalid capture_request_id');
  if (!Array.isArray(value.approved_origins) || value.approved_origins.length === 0) throw new TypeError('approved_origins must be non-empty');
  if (typeof value.recording_sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(value.recording_sha256)) throw new TypeError('invalid recording_sha256');
  if (typeof value.recording_content_ref !== 'string' || value.recording_content_ref.includes('..')) throw new TypeError('invalid recording_content_ref');
  if (!(value.browser_session_ref in HOST_SESSION_CONFIG)) throw new TypeError('unsupported browser session');
  if (value.authentication_status !== 'AUTH_READY') throw new TypeError('capture host requires AUTH_READY');
  if (value.privacy_mode !== PRIVACY_MODE) throw new TypeError('unsupported privacy mode');
  if (typeof value.raw_recording !== 'string') throw new TypeError('raw_recording must be a string');
  if (Buffer.byteLength(value.raw_recording, 'utf8') > CAPTURE_HOST_MAX_INPUT_BYTES) throw new TypeError('raw_recording exceeds byte bound');
  if (fingerprintRecording(value.raw_recording) !== value.recording_sha256) throw new TypeError('recording digest mismatch');
  return Object.freeze(structuredClone(value));
}

function canonicalCapturedAt(date = new Date()) {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export async function runHostCapture(value, {
  captureImpl = captureFlow,
  username = os.userInfo().username,
  capturedAt = canonicalCapturedAt(),
} = {}) {
  const input = validateHostCaptureInput(value);
  const config = HOST_SESSION_CONFIG[input.browser_session_ref];
  if (username !== config.username) {
    return Object.freeze({
      transport_status: 'succeeded',
      execution_surface: EXECUTION_SURFACE,
      capture_result: Object.freeze({ status: 'blocked', capture: null, failure: Object.freeze({ reason_code: 'browser-session-user-mismatch' }) }),
      side_effects_performed: false,
    });
  }
  const screenshotDir = resolve(config.captureRoot, input.capture_request_id);
  await mkdir(screenshotDir, { recursive: true, mode: 0o700 });
  const captureResult = await captureImpl({
    rawRecording: input.raw_recording,
    approvedOrigins: input.approved_origins,
    captureId: input.capture_request_id,
    capturedAt,
    userDataDir: config.profile,
    screenshotDir,
    authenticationStatus: input.authentication_status,
    headless: true,
    launchOptions: Object.freeze({ executablePath: '/usr/bin/chromium' }),
    captureTargetStyle: false,
  });
  return Object.freeze({
    transport_status: 'succeeded',
    execution_surface: EXECUTION_SURFACE,
    capture_result: captureResult,
    side_effects_performed: true,
  });
}

async function readStdin() {
  const chunks = [];
  let total = 0;
  for await (const chunk of process.stdin) {
    total += chunk.length;
    if (total > CAPTURE_HOST_MAX_INPUT_BYTES) throw new Error('capture host input exceeds byte bound');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString('utf8');
}

export async function main() {
  if (process.argv.length !== 2) throw new Error('capture host accepts no arguments');
  const raw = await readStdin();
  const parsed = JSON.parse(raw);
  const result = await runHostCapture(parsed);
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    process.stderr.write(`software tutorial capture refused: ${error instanceof Error ? error.message : 'unknown error'}\n`);
    process.exitCode = 64;
  });
}
