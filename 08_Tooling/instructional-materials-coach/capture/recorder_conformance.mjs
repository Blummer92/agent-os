import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';

export const REPLAY_VALIDATOR_NAME = '@puppeteer/replay';
export const SUPPORTED_REPLAY_VERSION = '4.0.2';

const require = createRequire(import.meta.url);

function bytesOf(rawRecording) {
  if (typeof rawRecording === 'string') return Buffer.from(rawRecording, 'utf8');
  if (Buffer.isBuffer(rawRecording)) return Buffer.from(rawRecording);
  if (rawRecording instanceof Uint8Array) return Buffer.from(rawRecording);
  throw new TypeError('rawRecording must be a string, Buffer, or Uint8Array');
}

function digest(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

function installedReplayVersion() {
  const entry = require.resolve(REPLAY_VALIDATOR_NAME);
  let directory = dirname(entry);
  while (true) {
    const candidate = join(directory, 'package.json');
    try {
      const metadata = JSON.parse(readFileSync(candidate, 'utf8'));
      if (metadata.name === REPLAY_VALIDATOR_NAME && typeof metadata.version === 'string') return metadata.version;
    } catch {}
    const parent = dirname(directory);
    if (parent === directory) break;
    directory = parent;
  }
  throw new Error('validator package metadata unavailable');
}

function result({ status, inputSha256, validatorVersion = null, parseStatus, diagnosticCodes }) {
  return Object.freeze({
    status,
    input_sha256: inputSha256,
    validator: Object.freeze({ name: REPLAY_VALIDATOR_NAME, version: validatorVersion }),
    parse_status: parseStatus,
    diagnostic_codes: Object.freeze([...diagnosticCodes]),
    behavioral_equivalence_proven: false,
  });
}

async function defaultReplayLoader() {
  return import(REPLAY_VALIDATOR_NAME);
}

export async function validateRecorderConformance(rawRecording, { loadReplay = defaultReplayLoader, resolveValidatorVersion = installedReplayVersion } = {}) {
  const bytes = bytesOf(rawRecording);
  const inputSha256 = digest(bytes);
  let parsed;
  try {
    parsed = JSON.parse(bytes.toString('utf8'));
  } catch {
    return result({ status: 'json-invalid', inputSha256, parseStatus: 'json-rejected', diagnosticCodes: ['json-parse-invalid'] });
  }

  let replay;
  try {
    replay = await loadReplay();
  } catch {
    return result({ status: 'validator-unavailable', inputSha256, parseStatus: 'not-run', diagnosticCodes: ['validator-unavailable'] });
  }
  if (!replay || typeof replay.parse !== 'function') {
    return result({ status: 'validator-error', inputSha256, parseStatus: 'not-run', diagnosticCodes: ['validator-api-invalid'] });
  }

  let validatorVersion;
  try {
    validatorVersion = resolveValidatorVersion();
  } catch {
    return result({ status: 'validator-error', inputSha256, parseStatus: 'not-run', diagnosticCodes: ['validator-version-unavailable'] });
  }
  if (validatorVersion !== SUPPORTED_REPLAY_VERSION) {
    return result({ status: 'validator-error', inputSha256, validatorVersion, parseStatus: 'not-run', diagnosticCodes: ['validator-version-mismatch'] });
  }

  try {
    replay.parse(parsed);
  } catch {
    return result({ status: 'recorder-invalid', inputSha256, validatorVersion, parseStatus: 'recorder-rejected', diagnosticCodes: ['recorder-format-invalid'] });
  }
  return result({ status: 'recorder-valid', inputSha256, validatorVersion, parseStatus: 'recorder-accepted', diagnosticCodes: [] });
}
