import { createHash } from 'node:crypto';
import {
  CAPTURE_FORMAT_VERSION,
  fingerprintRecording,
  validateAuthenticationStatus,
} from './safe_recording.mjs';

export const LIVE_CAPTURE_REQUEST_VERSION = 'software-tutorial-capture-request-v1';
export const LIVE_CAPTURE_RESULT_VERSION = 'software-tutorial-capture-request-result-v1';
export const BROWSER_SESSION_REF = 'adobe-express-default';
export const PRIVACY_MODE = 'sensitive-by-default';
export const EXECUTION_SURFACE = Object.freeze({
  kind: 'gce-iap',
  project: 'agent-os-502614',
  zone: 'us-central1-a',
  instance: 'agent-os-test',
});

const REQUEST_FIELDS = new Set([
  'format_version',
  'capture_request_id',
  'target_url',
  'allowed_origins',
  'recording_source',
  'browser_session_ref',
  'privacy_mode',
]);
const RECORDING_FIELDS = new Set(['kind', 'sha256', 'content_ref']);
const CAPABILITY_FIELDS = new Set(['browser_session_ref', 'authentication_status']);
const SHA256_RE = /^[a-f0-9]{64}$/;
const SAFE_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/;
const CONTENT_REF_RE = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/;

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value !== null && typeof value === 'object') {
    const out = {};
    for (const key of Object.keys(value).sort()) out[key] = canonicalize(value[key]);
    return out;
  }
  return value;
}

function fingerprint(value) {
  return createHash('sha256').update(JSON.stringify(canonicalize(value))).digest('hex');
}

function exactKeys(value, allowed, label) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`);
  }
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) throw new TypeError(`unsupported ${label} field: ${key}`);
  }
}

function exactHttpsOrigin(value) {
  if (typeof value !== 'string') throw new TypeError('origin must be a string');
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.origin !== value || url.username || url.password) {
    throw new TypeError(`approved origin must be an exact https origin: ${value}`);
  }
  return url.origin;
}

function surfaceMatches(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && value.kind === EXECUTION_SURFACE.kind
    && value.project === EXECUTION_SURFACE.project
    && value.zone === EXECUTION_SURFACE.zone
    && value.instance === EXECUTION_SURFACE.instance
    && Object.keys(value).length === 4;
}

export function validateLiveCaptureRequest(request) {
  exactKeys(request, REQUEST_FIELDS, 'request');
  if (request.format_version !== LIVE_CAPTURE_REQUEST_VERSION) throw new TypeError('unsupported live capture request version');
  if (typeof request.capture_request_id !== 'string' || !SAFE_ID_RE.test(request.capture_request_id)) throw new TypeError('invalid capture_request_id');
  if (!Array.isArray(request.allowed_origins) || request.allowed_origins.length === 0 || request.allowed_origins.length > 8) throw new TypeError('allowed_origins must be a bounded non-empty array');
  const origins = request.allowed_origins.map(exactHttpsOrigin);
  if (new Set(origins).size !== origins.length) throw new TypeError('allowed_origins must not contain duplicates');
  if (typeof request.target_url !== 'string') throw new TypeError('target_url must be a string');
  const target = new URL(request.target_url);
  if (target.protocol !== 'https:' || target.username || target.password) throw new TypeError('target_url must be an https URL without credentials');
  if (!origins.includes(target.origin)) throw new TypeError('target origin is not approved');

  exactKeys(request.recording_source, RECORDING_FIELDS, 'recording_source');
  if (request.recording_source.kind !== 'chrome-devtools-recorder') throw new TypeError('unsupported recording_source kind');
  if (typeof request.recording_source.sha256 !== 'string' || !SHA256_RE.test(request.recording_source.sha256)) throw new TypeError('recording_source.sha256 must be lowercase sha256');
  if (typeof request.recording_source.content_ref !== 'string' || !CONTENT_REF_RE.test(request.recording_source.content_ref)) throw new TypeError('recording_source.content_ref must be a bounded opaque reference');
  if (request.recording_source.content_ref.includes('..')) throw new TypeError('recording_source.content_ref may not traverse paths');
  if (request.browser_session_ref !== BROWSER_SESSION_REF) throw new TypeError('unsupported browser_session_ref');
  if (request.privacy_mode !== PRIVACY_MODE) throw new TypeError('unsupported privacy_mode');
  return Object.freeze({ ...structuredClone(request), allowed_origins: Object.freeze([...origins]) });
}

export function validateBrowserSessionCapability(capability) {
  exactKeys(capability, CAPABILITY_FIELDS, 'browser session capability');
  if (capability.browser_session_ref !== BROWSER_SESSION_REF) throw new TypeError('browser session capability does not match canonical session');
  validateAuthenticationStatus(capability.authentication_status);
  return Object.freeze(structuredClone(capability));
}

function blocked(request, requestFingerprint, authStatus, reasonCode, transportStatus = 'not-invoked') {
  return Object.freeze({
    format_version: LIVE_CAPTURE_RESULT_VERSION,
    capture_request_id: request.capture_request_id,
    request_fingerprint: requestFingerprint,
    execution_surface: EXECUTION_SURFACE,
    transport_status: transportStatus,
    capture_status: 'blocked',
    capture_ref: null,
    recording_sha256: request.recording_source.sha256,
    authentication_status: authStatus,
    privacy_state: PRIVACY_MODE,
    reason_codes: Object.freeze([reasonCode]),
    side_effects_performed: false,
  });
}

export async function runLiveCaptureRequest({
  request,
  rawRecording,
  browserSessionCapability,
  executionSurface = EXECUTION_SURFACE,
  invokeCapture,
  idempotencyLookup = async () => null,
  idempotencyRecord = async () => {},
}) {
  let normalized;
  try {
    normalized = validateLiveCaptureRequest(request);
  } catch {
    return Object.freeze({
      format_version: LIVE_CAPTURE_RESULT_VERSION,
      capture_request_id: typeof request?.capture_request_id === 'string' ? request.capture_request_id : null,
      request_fingerprint: null,
      execution_surface: EXECUTION_SURFACE,
      transport_status: 'not-invoked',
      capture_status: 'blocked',
      capture_ref: null,
      recording_sha256: typeof request?.recording_source?.sha256 === 'string' ? request.recording_source.sha256 : null,
      authentication_status: null,
      privacy_state: PRIVACY_MODE,
      reason_codes: Object.freeze(['request-invalid']),
      side_effects_performed: false,
    });
  }
  const requestFingerprint = fingerprint(normalized);
  if (!surfaceMatches(executionSurface)) return blocked(normalized, requestFingerprint, null, 'execution-surface-mismatch');

  let capability;
  try { capability = validateBrowserSessionCapability(browserSessionCapability); }
  catch { return blocked(normalized, requestFingerprint, null, 'browser-session-capability-missing'); }
  if (capability.authentication_status !== 'AUTH_READY') {
    return blocked(normalized, requestFingerprint, capability.authentication_status, `auth-${capability.authentication_status.slice(5).toLowerCase()}`);
  }

  let actualDigest;
  try { actualDigest = fingerprintRecording(rawRecording); }
  catch { return blocked(normalized, requestFingerprint, capability.authentication_status, 'recording-unavailable'); }
  if (actualDigest !== normalized.recording_source.sha256) return blocked(normalized, requestFingerprint, capability.authentication_status, 'recording-digest-mismatch');

  const prior = await idempotencyLookup(normalized.capture_request_id);
  if (prior !== null && prior !== undefined) {
    if (prior.request_fingerprint !== requestFingerprint) return blocked(normalized, requestFingerprint, capability.authentication_status, 'request-identity-conflict');
    return Object.freeze({ ...structuredClone(prior), transport_status: 'deduplicated', side_effects_performed: false, reason_codes: Object.freeze(['duplicate-request-reused']) });
  }
  if (typeof invokeCapture !== 'function') return blocked(normalized, requestFingerprint, capability.authentication_status, 'transport-unavailable');

  let transport;
  try {
    transport = await invokeCapture(Object.freeze({
      operation: 'captureFlow',
      execution_surface: EXECUTION_SURFACE,
      capture_request_id: normalized.capture_request_id,
      target_url: normalized.target_url,
      approved_origins: normalized.allowed_origins,
      recording_sha256: normalized.recording_source.sha256,
      recording_content_ref: normalized.recording_source.content_ref,
      browser_session_ref: normalized.browser_session_ref,
      authentication_status: capability.authentication_status,
      privacy_mode: normalized.privacy_mode,
      raw_recording: rawRecording,
    }));
  } catch {
    return blocked(normalized, requestFingerprint, capability.authentication_status, 'transport-failed', 'failed');
  }

  if (!transport || transport.transport_status !== 'succeeded' || !surfaceMatches(transport.execution_surface)) {
    return blocked(normalized, requestFingerprint, capability.authentication_status, 'transport-failed', transport?.transport_status ?? 'failed');
  }

  const captureResult = transport.capture_result;
  const capture = captureResult?.capture ?? null;
  const captureStatus = typeof captureResult?.status === 'string' ? captureResult.status : 'blocked';
  if (captureStatus !== 'valid') {
    return Object.freeze({
      format_version: LIVE_CAPTURE_RESULT_VERSION,
      capture_request_id: normalized.capture_request_id,
      request_fingerprint: requestFingerprint,
      execution_surface: EXECUTION_SURFACE,
      transport_status: 'succeeded',
      capture_status: captureStatus,
      capture_ref: null,
      recording_sha256: normalized.recording_source.sha256,
      authentication_status: capability.authentication_status,
      privacy_state: PRIVACY_MODE,
      reason_codes: Object.freeze(['capture-failed']),
      side_effects_performed: Boolean(transport.side_effects_performed),
    });
  }

  if (!capture || capture.format_version !== CAPTURE_FORMAT_VERSION || capture.capture_id !== normalized.capture_request_id || capture.source?.recording_sha256 !== normalized.recording_source.sha256) {
    return blocked(normalized, requestFingerprint, capability.authentication_status, 'result-identity-mismatch', 'succeeded');
  }

  const receipt = Object.freeze({
    format_version: LIVE_CAPTURE_RESULT_VERSION,
    capture_request_id: normalized.capture_request_id,
    request_fingerprint: requestFingerprint,
    execution_surface: EXECUTION_SURFACE,
    transport_status: 'succeeded',
    capture_status: 'valid',
    capture_ref: Object.freeze({
      format_version: capture.format_version,
      capture_id: capture.capture_id,
      recording_sha256: capture.source.recording_sha256,
    }),
    recording_sha256: normalized.recording_source.sha256,
    authentication_status: capability.authentication_status,
    privacy_state: PRIVACY_MODE,
    reason_codes: Object.freeze([]),
    side_effects_performed: Boolean(transport.side_effects_performed),
  });
  await idempotencyRecord(normalized.capture_request_id, receipt);
  return receipt;
}
