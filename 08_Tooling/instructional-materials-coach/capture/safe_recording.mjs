import { createHash } from 'node:crypto';

export const CAPTURE_FORMAT_VERSION = 'software-tutorial-capture-v1';
export const CAPTURE_FORMAT_VERSION_V2 = 'software-tutorial-capture-v2';
export const REPLAY_VERSION = '4.0.2';
export const PUPPETEER_VERSION = '25.3.0';

/**
 * Frozen `getComputedStyle` allowlist for optional capture-v2 target-style
 * evidence (#1485). No DOM traversal and no per-child style trees: this reads
 * only the already-resolved target handle.
 */
export const TARGET_STYLE_PROPERTY_ALLOWLIST = Object.freeze([
  'color',
  'backgroundColor',
  'opacity',
  'fontFamily',
  'fontSize',
  'fontWeight',
  'fontStyle',
  'lineHeight',
  'letterSpacing',
  'borderRadius',
  'backgroundImage',
  'boxShadow',
  'textShadow',
  'transform',
]);

export const AUTH_STATUSES = Object.freeze([
  'AUTH_READY',
  'AUTH_REQUIRED',
  'AUTH_EXPIRED',
  'AUTH_BLOCKED',
]);

const AUTH_REASON_BY_STATUS = Object.freeze({
  AUTH_REQUIRED: 'authority-auth-required',
  AUTH_EXPIRED: 'authority-auth-expired',
  AUTH_BLOCKED: 'authority-auth-blocked',
});

export const CAPTURE_STATUSES = Object.freeze([
  'valid',
  'invalid',
  'blocked',
  'stale',
  'manual-review-required',
]);

export const CAPTURE_REASON_CODES = Object.freeze([
  'artifact-action-missing',
  'artifact-recording-invalid',
  'artifact-recording-unknown-field',
  'artifact-step-unsupported',
  'asset-sensitive-content',
  'authority-auth-blocked',
  'authority-auth-expired',
  'authority-auth-required',
  'quality-replay-failed',
  'quality-target-ambiguous',
  'quality-target-unresolved',
]);

export const ALLOWED_STEP_TYPES = new Set([
  'setViewport', 'navigate', 'click', 'doubleClick', 'change', 'hover',
  'scroll', 'keyDown', 'keyUp', 'waitForElement',
]);

export const REJECTED_STEP_TYPES = new Set([
  'waitForExpression', 'customStep', 'emulateNetworkConditions', 'close',
]);

const SENSITIVE_KEY_RE = /(password|passwd|secret|token|authorization|cookie|credential|mfa|otp|session)/i;
const ACCOUNT_EMAIL_RE = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i;
const MAX_RECORDING_BYTES = 5 * 1024 * 1024;
const MAX_STEPS = 200;
const MAX_RECURSION_DEPTH = 12;
const KNOWN_TOP_LEVEL_FIELDS = new Set(['title', 'timeout', 'selectorAttribute', 'steps']);
const COMMON_STEP_FIELDS = new Set(['type', 'timeout', 'assertedEvents', 'target', 'frame']);
const STEP_FIELDS = Object.freeze({
  setViewport: new Set([...COMMON_STEP_FIELDS, 'width', 'height', 'deviceScaleFactor', 'isMobile', 'hasTouch', 'isLandscape']),
  navigate: new Set([...COMMON_STEP_FIELDS, 'url']),
  click: new Set([...COMMON_STEP_FIELDS, 'selectors', 'deviceType', 'button', 'offsetX', 'offsetY', 'duration']),
  doubleClick: new Set([...COMMON_STEP_FIELDS, 'selectors', 'deviceType', 'button', 'offsetX', 'offsetY', 'duration']),
  change: new Set([...COMMON_STEP_FIELDS, 'selectors', 'value']),
  hover: new Set([...COMMON_STEP_FIELDS, 'selectors']),
  scroll: new Set([...COMMON_STEP_FIELDS, 'selectors', 'x', 'y']),
  keyDown: new Set([...COMMON_STEP_FIELDS, 'key']),
  keyUp: new Set([...COMMON_STEP_FIELDS, 'key']),
  waitForElement: new Set([...COMMON_STEP_FIELDS, 'selectors', 'operator', 'count', 'visible', 'properties', 'attributes']),
});

function rawBytes(rawRecording) {
  if (typeof rawRecording === 'string') return Buffer.from(rawRecording, 'utf8');
  if (Buffer.isBuffer(rawRecording)) return rawRecording;
  if (rawRecording instanceof Uint8Array) return Buffer.from(rawRecording);
  throw new TypeError('recording must be a string, Buffer, or Uint8Array');
}

export function validateAuthenticationStatus(status) {
  if (!AUTH_STATUSES.includes(status)) throw new TypeError(`unsupported authentication status: ${status}`);
  return status;
}

export function authenticationBlocker(status) {
  validateAuthenticationStatus(status);
  return status === 'AUTH_READY' ? null : AUTH_REASON_BY_STATUS[status];
}

export function fingerprintRecording(rawRecording) {
  return createHash('sha256').update(rawBytes(rawRecording)).digest('hex');
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value !== null && typeof value === 'object') {
    const result = {};
    for (const key of Object.keys(value).sort()) result[key] = canonicalize(value[key]);
    return result;
  }
  return value;
}

export function fingerprintAction(step) {
  return createHash('sha256').update(JSON.stringify(canonicalize(step))).digest('hex');
}

const RGBA_COMMA_RE = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/i;
const RGBA_SLASH_RE = /^rgba?\(\s*(\d+)\s+(\d+)\s+(\d+)\s*(?:\/\s*([\d.]+%?)\s*)?\)$/i;

/**
 * Parse a `getComputedStyle` color string into canonical RGBA. Browsers resolve
 * `color`/`background-color` to `rgb()`/`rgba()` forms, so this recognizes only
 * those exact canonical shapes; it is not a general CSS color parser and returns
 * null rather than guessing at anything else (including named colors, which a
 * resolved computed style never emits).
 */
export function parseComputedColorToRgba(rawValue) {
  if (typeof rawValue !== 'string') return null;
  const value = rawValue.trim();
  if (value === 'transparent') return Object.freeze([0, 0, 0, 0]);
  const match = RGBA_COMMA_RE.exec(value) ?? RGBA_SLASH_RE.exec(value);
  if (!match) return null;
  const [, r, g, b, a] = match;
  const channels = [r, g, b].map(Number);
  if (channels.some((channel) => !Number.isInteger(channel) || channel < 0 || channel > 255)) return null;
  let alpha = 1;
  if (a !== undefined) {
    alpha = a.endsWith('%') ? Number(a.slice(0, -1)) / 100 : Number(a);
    if (!Number.isFinite(alpha) || alpha < 0 || alpha > 1) return null;
  }
  return Object.freeze([...channels, alpha]);
}

function splitTopLevelCommas(value) {
  const parts = [];
  let depth = 0;
  let current = '';
  for (const char of value) {
    if (char === '(') depth += 1;
    if (char === ')') depth -= 1;
    if (char === ',' && depth === 0) {
      parts.push(current.trim());
      current = '';
    } else {
      current += char;
    }
  }
  if (current.trim().length > 0) parts.push(current.trim());
  return parts;
}

const GRADIENT_LAYER_RE = /^(?:repeating-)?(?:linear|radial|conic)-gradient\(.*\)$/i;

/**
 * Sanitize a `background-image` computed value before persistence (#1485).
 * Bounded CSS gradients are retained as raw computed strings; `url(...)`,
 * `blob:`, `data:`, and any other unsupported function become null rather than
 * persisting external/private resource identity. This intentionally does not
 * parse gradient stops or build a general CSS value parser: it only splits
 * top-level comma-separated layers so multi-layer backgrounds cannot smuggle an
 * unsafe layer past a safe one.
 */
export function sanitizeBackgroundImage(rawValue) {
  if (typeof rawValue !== 'string') return null;
  const value = rawValue.trim();
  if (value.length === 0) return null;
  if (value === 'none') return 'none';
  const layers = splitTopLevelCommas(value);
  if (layers.length === 0) return null;
  for (const layer of layers) {
    if (/url\(|blob:|data:/i.test(layer)) return null;
    if (!GRADIENT_LAYER_RE.test(layer)) return null;
  }
  return value;
}

/**
 * Normalize raw bounded `getComputedStyle` strings into persisted
 * `TargetStyleEvidence` (#1485). Only `TARGET_STYLE_PROPERTY_ALLOWLIST`
 * properties are read. A missing/unavailable property becomes null; nothing
 * here fabricates a value the browser did not report.
 */
export function buildTargetStyleEvidence(rectNormalized, rawComputedStyle) {
  if (
    !Array.isArray(rectNormalized) ||
    rectNormalized.length !== 4 ||
    rectNormalized.some((value) => typeof value !== 'number' || !Number.isFinite(value))
  ) {
    throw new TypeError('rectNormalized must be four finite numbers');
  }
  const raw = rawComputedStyle && typeof rawComputedStyle === 'object' ? rawComputedStyle : {};
  const str = (key) => (typeof raw[key] === 'string' && raw[key].trim().length > 0 ? raw[key] : null);
  const num = (key) => {
    const value = str(key);
    if (value === null) return null;
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  return Object.freeze({
    rect_normalized: Object.freeze([...rectNormalized]),
    color_rgba: parseComputedColorToRgba(raw.color),
    background_rgba: parseComputedColorToRgba(raw.backgroundColor),
    opacity: num('opacity'),
    font_family: str('fontFamily'),
    font_size_px: num('fontSize'),
    font_weight: num('fontWeight'),
    font_style: str('fontStyle'),
    line_height: str('lineHeight'),
    letter_spacing: str('letterSpacing'),
    border_radius: str('borderRadius'),
    background_image: sanitizeBackgroundImage(raw.backgroundImage),
    box_shadow: str('boxShadow'),
    text_shadow: str('textShadow'),
    transform: str('transform'),
  });
}

function issue(status, reasonCode, detail, sourceIndex = null) {
  if (!CAPTURE_STATUSES.includes(status)) throw new Error(`unsupported capture status: ${status}`);
  if (!CAPTURE_REASON_CODES.includes(reasonCode)) throw new Error(`unsupported capture reason code: ${reasonCode}`);
  return Object.freeze({ status, reason_code: reasonCode, detail, source_index: sourceIndex });
}

function inspectSensitiveContent(value, path = '$', depth = 0, findings = []) {
  if (depth > MAX_RECURSION_DEPTH || findings.length >= 20) return findings;
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) inspectSensitiveContent(value[index], `${path}[${index}]`, depth + 1, findings);
    return findings;
  }
  if (value !== null && typeof value === 'object') {
    for (const [key, child] of Object.entries(value)) {
      if (SENSITIVE_KEY_RE.test(key)) findings.push(`${path}.${key}`);
      inspectSensitiveContent(child, `${path}.${key}`, depth + 1, findings);
    }
    return findings;
  }
  if (typeof value === 'string' && ACCOUNT_EMAIL_RE.test(value)) findings.push(path);
  return findings;
}

function normalizeApprovedOrigins(approvedOrigins) {
  if (!Array.isArray(approvedOrigins) || approvedOrigins.length === 0) throw new TypeError('approvedOrigins must be a non-empty array of exact origins');
  return new Set(approvedOrigins.map((origin) => {
    const parsed = new URL(origin);
    if (parsed.origin !== origin || parsed.protocol !== 'https:') throw new TypeError(`approved origin must be an exact https origin: ${origin}`);
    return parsed.origin;
  }));
}

function selectorsFor(step) {
  return Array.isArray(step.selectors) ? structuredClone(step.selectors) : [];
}

function normalizeStep(step, sourceIndex) {
  const normalized = {
    source_index: sourceIndex,
    source_fingerprint: fingerprintAction(step),
    type: step.type,
    selector_alternatives: selectorsFor(step),
  };
  if (typeof step.offsetX === 'number') normalized.recorded_offset_x = step.offsetX;
  if (typeof step.offsetY === 'number') normalized.recorded_offset_y = step.offsetY;
  if (step.type === 'setViewport') normalized.viewport = { width: step.width, height: step.height, deviceScaleFactor: step.deviceScaleFactor };
  return Object.freeze(normalized);
}

export function validateRecording(rawRecording, { approvedOrigins } = {}) {
  const bytes = rawBytes(rawRecording);
  const recordingSha256 = fingerprintRecording(bytes);
  const findings = [];
  let parsed;

  if (bytes.length === 0 || bytes.length > MAX_RECORDING_BYTES) {
    return Object.freeze({ status: 'invalid', recording_sha256: recordingSha256, recording: null, actions: [], findings: [issue('invalid', 'artifact-recording-invalid', 'recording byte length is outside the bounded input range')] });
  }

  try { parsed = JSON.parse(bytes.toString('utf8')); }
  catch { return Object.freeze({ status: 'invalid', recording_sha256: recordingSha256, recording: null, actions: [], findings: [issue('invalid', 'artifact-recording-invalid', 'recording is not valid JSON')] }); }

  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) findings.push(issue('invalid', 'artifact-recording-invalid', 'recording root must be an object'));
  if (findings.length === 0) {
    for (const key of Object.keys(parsed)) if (!KNOWN_TOP_LEVEL_FIELDS.has(key)) findings.push(issue('invalid', 'artifact-recording-unknown-field', `unsupported top-level field: ${key}`));
  }
  if (findings.length === 0 && (!Array.isArray(parsed.steps) || parsed.steps.length === 0 || parsed.steps.length > MAX_STEPS)) findings.push(issue('invalid', 'artifact-action-missing', 'recording must contain a bounded non-empty steps array'));

  let allowedOrigins;
  try { allowedOrigins = normalizeApprovedOrigins(approvedOrigins); }
  catch (error) { findings.push(issue('blocked', 'artifact-recording-invalid', error.message)); }

  if (findings.length === 0) {
    const sensitivePaths = inspectSensitiveContent(parsed);
    if (sensitivePaths.length > 0) findings.push(issue('manual-review-required', 'asset-sensitive-content', `sensitive content indicators at: ${sensitivePaths.join(', ')}`));
  }

  const actions = [];
  if (Array.isArray(parsed?.steps)) {
    for (let index = 0; index < parsed.steps.length; index += 1) {
      const step = parsed.steps[index];
      if (step === null || typeof step !== 'object' || Array.isArray(step) || typeof step.type !== 'string') {
        findings.push(issue('invalid', 'artifact-recording-invalid', 'step must be an object with a string type', index));
        continue;
      }
      if (REJECTED_STEP_TYPES.has(step.type) || !ALLOWED_STEP_TYPES.has(step.type)) {
        findings.push(issue('invalid', 'artifact-step-unsupported', `unsupported Recorder step type: ${step.type}`, index));
        continue;
      }
      const unknownFields = Object.keys(step).filter((key) => !STEP_FIELDS[step.type].has(key));
      if (unknownFields.length > 0) {
        findings.push(issue('invalid', 'artifact-recording-unknown-field', `unsupported field(s) on ${step.type}: ${unknownFields.sort().join(', ')}`, index));
        continue;
      }
      if (step.type === 'navigate') {
        try {
          const url = new URL(step.url);
          if (!allowedOrigins?.has(url.origin)) {
            findings.push(issue('blocked', 'artifact-recording-invalid', `navigation origin is not approved: ${url.origin}`, index));
            continue;
          }
        } catch {
          findings.push(issue('invalid', 'artifact-recording-invalid', 'navigate step has an invalid URL', index));
          continue;
        }
      }
      actions.push(normalizeStep(step, index));
    }
  }

  const status = findings.some((finding) => finding.status === 'blocked') ? 'blocked'
    : findings.some((finding) => finding.status === 'manual-review-required') ? 'manual-review-required'
      : findings.length > 0 ? 'invalid' : 'valid';

  return Object.freeze({ status, recording_sha256: recordingSha256, recording: parsed === undefined ? null : structuredClone(parsed), actions: Object.freeze(actions), findings: Object.freeze(findings) });
}

function stripTargetStyle(action) {
  const { target_style, ...rest } = action;
  return rest;
}

/**
 * Build the capture envelope. Defaults to v1 with byte-identical shape to
 * before #1485: `formatVersion` must be passed explicitly to opt into v2, and
 * v1 output never carries `target_style` even if the caller's `actionEvidence`
 * happens to include it, so v1 stays unaffected by v2 support existing.
 */
export function buildCaptureEnvelope({
  captureId,
  capturedAt,
  validation,
  actionEvidence = [],
  formatVersion = CAPTURE_FORMAT_VERSION,
}) {
  if (formatVersion !== CAPTURE_FORMAT_VERSION && formatVersion !== CAPTURE_FORMAT_VERSION_V2) {
    throw new TypeError(`unsupported capture format version: ${formatVersion}`);
  }
  if (validation?.status !== 'valid') throw new Error('capture envelope requires a valid preflight result');
  if (typeof captureId !== 'string' || captureId.length === 0) throw new TypeError('captureId is required');
  if (typeof capturedAt !== 'string' || Number.isNaN(Date.parse(capturedAt))) throw new TypeError('capturedAt must be an ISO timestamp string');
  const viewportAction = validation.actions.find((action) => action.type === 'setViewport');
  const actions = formatVersion === CAPTURE_FORMAT_VERSION_V2
    ? actionEvidence.map((action) => ({ ...action, target_style: action.target_style ?? null }))
    : actionEvidence.map(stripTargetStyle);
  return Object.freeze({
    format_version: formatVersion,
    capture_id: captureId,
    captured_at: capturedAt,
    source: Object.freeze({ kind: 'chrome-devtools-recorder', recording_sha256: validation.recording_sha256 }),
    runtime: Object.freeze({ replay_version: REPLAY_VERSION, puppeteer_version: PUPPETEER_VERSION }),
    viewport: viewportAction?.viewport ?? null,
    actions: Object.freeze(structuredClone(actions)),
  });
}
