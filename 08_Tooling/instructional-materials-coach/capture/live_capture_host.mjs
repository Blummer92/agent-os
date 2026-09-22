import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import { resolve } from 'node:path';
import puppeteer from 'puppeteer';

import { captureFlow } from './replay_capture.mjs';
import { validateFileInputArtifacts } from './file_input_bindings.mjs';
import {
  BROWSER_SESSION_REF,
  CANVA_BROWSER_SESSION_REF,
  EXECUTION_SURFACE,
  PRIVACY_MODE,
} from './live_capture_request.mjs';
import { fingerprintRecording } from './safe_recording.mjs';

export const CAPTURE_HOST_INPUT_VERSION = 'software-tutorial-capture-host-input-v1';
export const CAPTURE_HOST_MAX_INPUT_BYTES = 32 * 1024 * 1024;
export const CAPTURE_HOST_MAX_SCREENSHOTS = 256;
export const CAPTURE_HOST_MAX_SCREENSHOT_BYTES = 16 * 1024 * 1024;

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
  'file_input_artifacts',
]);

const HOST_SESSION_CONFIG = Object.freeze({
  [BROWSER_SESSION_REF]: Object.freeze({
    username: 'agent-os-capture',
    profile: '/var/lib/agent-os/capture-home/.agent-os/browser-profiles/adobe-express',
    authProbeUrl: 'https://new.express.adobe.com/your-stuff/files',
    expectedOrigin: 'https://new.express.adobe.com',
  }),
  [CANVA_BROWSER_SESSION_REF]: Object.freeze({
    username: 'agent-os-canva-capture',
    profile: '/var/lib/agent-os/canva-capture-home/.agent-os/browser-profiles/canva',
    authProbeUrl: 'https://www.canva.com/projects/',
    expectedOrigin: 'https://www.canva.com',
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
  const fileInputArtifacts = validateFileInputArtifacts(value.raw_recording, value.file_input_artifacts ?? []);
  return Object.freeze({ ...structuredClone(value), file_input_artifacts: fileInputArtifacts });
}

function canonicalCapturedAt(date = new Date()) {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

async function collectScreenshots(screenshotDir) {
  const names = (await readdir(screenshotDir)).filter((name) => /^[0-9]{3}-(?:before|after)\.png$/.test(name)).sort();
  if (names.length > CAPTURE_HOST_MAX_SCREENSHOTS) throw new Error('capture screenshot count exceeds bound');
  const screenshots = [];
  for (const filename of names) {
    const bytes = await readFile(resolve(screenshotDir, filename));
    if (bytes.length > CAPTURE_HOST_MAX_SCREENSHOT_BYTES) throw new Error('capture screenshot exceeds byte bound');
    screenshots.push(Object.freeze({ filename, content_base64: bytes.toString('base64') }));
  }
  return Object.freeze(screenshots);
}

export async function probeHostAuthentication(config, {
  puppeteerImpl = puppeteer,
} = {}) {
  let browser = null;
  try {
    browser = await puppeteerImpl.launch({
      executablePath: '/usr/bin/chromium',
      userDataDir: config.profile,
      headless: true,
      args: ['--no-first-run', '--no-default-browser-check', '--disable-session-crashed-bubble'],
    });
    const pages = await browser.pages();
    const page = pages[0] ?? await browser.newPage();
    await page.goto(config.authProbeUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
    const observed = new URL(page.url());
    const route = `${observed.pathname}${observed.search}`.toLowerCase();
    if (observed.origin !== config.expectedOrigin || /(?:login|log-in|signin|sign-in|signup|sign-up|auth)/.test(route)) return 'AUTH_REQUIRED';
    const body = await page.evaluate(() => document.body?.innerText?.slice(0, 5000) ?? '');
    if (/\blog in\b/i.test(body) && /\bsign up\b/i.test(body) && !/\bprojects\b|\byour stuff\b/i.test(body)) return 'AUTH_REQUIRED';
    return 'AUTH_READY';
  } catch {
    return 'AUTH_BLOCKED';
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
}

function authBlockedResult(status) {
  const reason = status === 'AUTH_REQUIRED' ? 'auth-required'
    : status === 'AUTH_EXPIRED' ? 'auth-expired'
      : 'auth-blocked';
  return Object.freeze({
    transport_status: 'succeeded',
    execution_surface: EXECUTION_SURFACE,
    capture_result: Object.freeze({
      status: 'blocked',
      capture: null,
      authentication_status: status,
      failure: Object.freeze({ reason_code: reason }),
    }),
    screenshots: Object.freeze([]),
    evidence_persisted: false,
    side_effects_performed: false,
  });
}

export async function runHostCapture(value, {
  captureImpl = captureFlow,
  authenticationProbeImpl = probeHostAuthentication,
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
      screenshots: Object.freeze([]),
      evidence_persisted: false,
      side_effects_performed: false,
    });
  }

  const currentAuth = await authenticationProbeImpl(config);
  if (currentAuth !== 'AUTH_READY') return authBlockedResult(currentAuth);

  const runtimeRoot = await mkdtemp('/dev/shm/agent-os-software-tutorial-capture-');
  const screenshotDir = resolve(runtimeRoot, 'screenshots');
  const uploadDir = resolve(runtimeRoot, 'file-inputs');
  let captureResult;
  let screenshots = Object.freeze([]);
  try {
    await mkdir(screenshotDir, { recursive: true, mode: 0o700 });
    await mkdir(uploadDir, { recursive: true, mode: 0o700 });
    const fileInputBindings = [];
    for (const artifact of input.file_input_artifacts) {
      const path = resolve(uploadDir, `${String(artifact.source_index).padStart(3, '0')}-${artifact.filename}`);
      await writeFile(path, Buffer.from(artifact.content_base64, 'base64'), { mode: 0o600 });
      fileInputBindings.push(Object.freeze({
        source_index: artifact.source_index,
        source_fingerprint: artifact.source_fingerprint,
        content_ref: artifact.content_ref,
        sha256: artifact.sha256,
        filename: artifact.filename,
        path,
      }));
    }
    captureResult = await captureImpl({
      rawRecording: input.raw_recording,
      approvedOrigins: input.approved_origins,
      captureId: input.capture_request_id,
      capturedAt,
      userDataDir: config.profile,
      screenshotDir,
      authenticationStatus: currentAuth,
      headless: true,
      launchOptions: Object.freeze({ executablePath: '/usr/bin/chromium' }),
      captureTargetStyle: false,
      fileInputBindings,
    });
    screenshots = await collectScreenshots(screenshotDir);
  } finally {
    await rm(runtimeRoot, { recursive: true, force: true });
  }

  return Object.freeze({
    transport_status: 'succeeded',
    execution_surface: EXECUTION_SURFACE,
    capture_result: captureResult,
    screenshots,
    evidence_persisted: false,
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
