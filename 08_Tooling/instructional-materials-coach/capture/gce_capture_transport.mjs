import { spawn } from 'node:child_process';

import {
  BROWSER_SESSION_REF,
  BROWSER_SESSION_REFS,
  CANVA_BROWSER_SESSION_REF,
  EXECUTION_SURFACE,
  PRIVACY_MODE,
} from './live_capture_request.mjs';

export const CAPTURE_HOST_ENTRYPOINTS = Object.freeze({
  [BROWSER_SESSION_REF]: '/usr/local/libexec/agent-os-adobe-software-tutorial-capture',
  [CANVA_BROWSER_SESSION_REF]: '/usr/local/libexec/agent-os-canva-software-tutorial-capture',
});
export const CAPTURE_TRANSPORT_MAX_INPUT_BYTES = 32 * 1024 * 1024;
export const CAPTURE_TRANSPORT_MAX_OUTPUT_BYTES = 128 * 1024 * 1024;
export const CAPTURE_TRANSPORT_TIMEOUT_MS = 120_000;

const TRANSPORT_FIELDS = new Set([
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
  'file_input_artifacts',
]);

function exactKeys(value, allowed, label) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`);
  }
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) throw new TypeError(`unsupported ${label} field: ${key}`);
  }
}

function surfaceMatches(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && value.kind === EXECUTION_SURFACE.kind
    && value.project === EXECUTION_SURFACE.project
    && value.zone === EXECUTION_SURFACE.zone
    && value.instance === EXECUTION_SURFACE.instance
    && Object.keys(value).length === 4;
}

function validateTransportPayload(payload) {
  exactKeys(payload, TRANSPORT_FIELDS, 'capture transport payload');
  if (payload.operation !== 'captureFlow') throw new TypeError('unsupported capture operation');
  if (!surfaceMatches(payload.execution_surface)) throw new TypeError('execution surface mismatch');
  if (!BROWSER_SESSION_REFS.includes(payload.browser_session_ref)) throw new TypeError('unsupported browser session');
  if (payload.authentication_status !== 'AUTH_READY') throw new TypeError('capture transport requires AUTH_READY');
  if (payload.privacy_mode !== PRIVACY_MODE) throw new TypeError('unsupported privacy mode');
  if (typeof payload.raw_recording !== 'string') throw new TypeError('raw_recording must be a string');
  const encoded = Buffer.from(JSON.stringify(payload), 'utf8');
  if (encoded.length > CAPTURE_TRANSPORT_MAX_INPUT_BYTES) throw new TypeError('capture transport input exceeds byte bound');
  return encoded;
}

export function captureHostEntrypoint(browserSessionRef) {
  if (!BROWSER_SESSION_REFS.includes(browserSessionRef)) throw new TypeError('unsupported browser session');
  return CAPTURE_HOST_ENTRYPOINTS[browserSessionRef];
}

export function captureGcloudArgv(browserSessionRef) {
  const entrypoint = captureHostEntrypoint(browserSessionRef);
  return Object.freeze([
    'compute', 'ssh', EXECUTION_SURFACE.instance,
    '--project', EXECUTION_SURFACE.project,
    '--zone', EXECUTION_SURFACE.zone,
    '--tunnel-through-iap',
    '--quiet',
    '--command', `sudo -n ${entrypoint}`,
  ]);
}

function collectStream(stream, maximum, label) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    stream.on('data', (chunk) => {
      size += chunk.length;
      if (size > maximum) {
        reject(new Error(`${label} exceeds byte bound`));
        return;
      }
      chunks.push(chunk);
    });
    stream.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    stream.on('error', reject);
  });
}

export async function invokeGceCapture(payload, {
  spawnImpl = spawn,
  timeoutMs = CAPTURE_TRANSPORT_TIMEOUT_MS,
} = {}) {
  const body = validateTransportPayload(payload);
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > CAPTURE_TRANSPORT_TIMEOUT_MS) {
    throw new TypeError('timeoutMs is outside the bounded transport limit');
  }

  const child = spawnImpl('gcloud', captureGcloudArgv(payload.browser_session_ref), {
    shell: false,
    stdio: ['pipe', 'pipe', 'pipe'],
    env: process.env,
  });
  const stdoutPromise = collectStream(child.stdout, CAPTURE_TRANSPORT_MAX_OUTPUT_BYTES, 'capture transport stdout');
  const stderrPromise = collectStream(child.stderr, 64 * 1024, 'capture transport stderr');
  child.stdin.end(Buffer.concat([body, Buffer.from('\n')]));

  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    child.kill('SIGKILL');
  }, timeoutMs);

  const exitCode = await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', resolve);
  });
  clearTimeout(timer);
  const [stdout] = await Promise.all([stdoutPromise, stderrPromise]);
  if (timedOut) throw new Error('capture transport timed out');
  if (exitCode !== 0) throw new Error('capture host invocation failed');

  let result;
  try { result = JSON.parse(stdout); }
  catch { throw new Error('capture host response was not JSON'); }
  if (result === null || typeof result !== 'object' || Array.isArray(result)) throw new Error('capture host response must be an object');
  if (result.transport_status !== 'succeeded' || !surfaceMatches(result.execution_surface)) throw new Error('capture host response identity mismatch');
  if (result.evidence_persisted !== false) throw new Error('capture host must return ephemeral evidence only');
  if (!Array.isArray(result.screenshots) || result.screenshots.length > 256) throw new Error('capture host screenshot evidence is invalid');
  for (const screenshot of result.screenshots) {
    if (screenshot === null || typeof screenshot !== 'object' || Array.isArray(screenshot)
        || typeof screenshot.filename !== 'string'
        || !/^[0-9]{3}-(?:before|after)\.png$/.test(screenshot.filename)
        || typeof screenshot.content_base64 !== 'string') {
      throw new Error('capture host screenshot evidence is invalid');
    }
  }
  return Object.freeze(structuredClone(result));
}
