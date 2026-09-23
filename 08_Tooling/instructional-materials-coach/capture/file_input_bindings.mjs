import { createHash } from 'node:crypto';
import { basename } from 'node:path';

import {
  fingerprintAction,
  fingerprintRecording,
} from './safe_recording.mjs';

export const FILE_INPUT_ARTIFACT_MAX_BYTES = 8 * 1024 * 1024;
export const FILE_INPUT_ARTIFACT_MAX_COUNT = 8;
export const FILE_INPUT_ARTIFACT_MAX_TOTAL_BYTES = 16 * 1024 * 1024;

const SHA256_RE = /^[a-f0-9]{64}$/;
const CONTENT_REF_RE = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/;
const SAFE_FILENAME_RE = /^[A-Za-z0-9][A-Za-z0-9._() -]{0,159}$/;
const ARTIFACT_FIELDS = new Set([
  'source_index',
  'source_fingerprint',
  'content_ref',
  'sha256',
  'filename',
  'content_base64',
]);
const MATERIALIZED_FIELDS = new Set([
  'source_index',
  'source_fingerprint',
  'content_ref',
  'sha256',
  'filename',
  'path',
]);

function exactKeys(value, allowed, label) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`);
  }
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) throw new TypeError(`unsupported ${label} field: ${key}`);
  }
}

function decodeBase64(value) {
  if (typeof value !== 'string' || value.length === 0) throw new TypeError('file input content_base64 is required');
  const bytes = Buffer.from(value, 'base64');
  if (bytes.length === 0 || bytes.toString('base64') !== value.replace(/\s+/g, '')) {
    throw new TypeError('file input content_base64 must be canonical base64');
  }
  return bytes;
}

function assertCommonArtifactFields(artifact) {
  if (!Number.isInteger(artifact.source_index) || artifact.source_index < 0) throw new TypeError('file input source_index must be a non-negative integer');
  if (typeof artifact.source_fingerprint !== 'string' || !SHA256_RE.test(artifact.source_fingerprint)) throw new TypeError('file input source_fingerprint must be lowercase sha256');
  if (typeof artifact.content_ref !== 'string' || !CONTENT_REF_RE.test(artifact.content_ref) || artifact.content_ref.includes('..')) throw new TypeError('file input content_ref must be a bounded opaque reference');
  if (typeof artifact.sha256 !== 'string' || !SHA256_RE.test(artifact.sha256)) throw new TypeError('file input sha256 must be lowercase sha256');
  if (typeof artifact.filename !== 'string' || !SAFE_FILENAME_RE.test(artifact.filename) || basename(artifact.filename) !== artifact.filename) throw new TypeError('file input filename must be a bounded basename');
}

export function isRecordedFileInputStep(step) {
  return step?.type === 'change'
    && typeof step.value === 'string'
    && /^[A-Za-z]:\\fakepath\\[^\\/]+$/i.test(step.value);
}

function parsedRecording(rawRecording) {
  const text = Buffer.isBuffer(rawRecording) || rawRecording instanceof Uint8Array
    ? Buffer.from(rawRecording).toString('utf8')
    : rawRecording;
  if (typeof text !== 'string') throw new TypeError('recording must be text or bytes');
  return JSON.parse(text);
}

function validateActionIdentity(recording, artifact) {
  const step = recording.steps?.[artifact.source_index];
  if (!step || !isRecordedFileInputStep(step)) throw new TypeError('file input binding does not reference a recorded file-input change step');
  if (fingerprintAction(step) !== artifact.source_fingerprint) throw new TypeError('file input source fingerprint mismatch');
}

export function validateFileInputArtifacts(rawRecording, artifacts = []) {
  if (!Array.isArray(artifacts) || artifacts.length > FILE_INPUT_ARTIFACT_MAX_COUNT) throw new TypeError('file input artifacts must be a bounded array');
  const recording = parsedRecording(rawRecording);
  const fileStepIndexes = (recording.steps ?? [])
    .map((step, index) => (isRecordedFileInputStep(step) ? index : null))
    .filter((index) => index !== null);

  const seen = new Set();
  let totalBytes = 0;
  const normalized = [];
  for (const artifact of artifacts) {
    exactKeys(artifact, ARTIFACT_FIELDS, 'file input artifact');
    assertCommonArtifactFields(artifact);
    if (seen.has(artifact.source_index)) throw new TypeError('duplicate file input source_index');
    seen.add(artifact.source_index);
    validateActionIdentity(recording, artifact);
    const bytes = decodeBase64(artifact.content_base64);
    if (bytes.length > FILE_INPUT_ARTIFACT_MAX_BYTES) throw new TypeError('file input artifact exceeds byte bound');
    totalBytes += bytes.length;
    if (totalBytes > FILE_INPUT_ARTIFACT_MAX_TOTAL_BYTES) throw new TypeError('file input artifacts exceed total byte bound');
    const digest = createHash('sha256').update(bytes).digest('hex');
    if (digest !== artifact.sha256) throw new TypeError('file input artifact digest mismatch');
    normalized.push(Object.freeze({ ...structuredClone(artifact), content_base64: bytes.toString('base64') }));
  }

  if (fileStepIndexes.length !== normalized.length || fileStepIndexes.some((index) => !seen.has(index))) {
    throw new TypeError('every recorded file-input step requires exactly one bounded artifact');
  }

  return Object.freeze(normalized);
}

export function fileInputArtifactIdentity(artifact) {
  return Object.freeze({
    source_index: artifact.source_index,
    source_fingerprint: artifact.source_fingerprint,
    content_ref: artifact.content_ref,
    sha256: artifact.sha256,
    filename: artifact.filename,
  });
}

export function validateMaterializedFileInputBindings(rawRecording, bindings = []) {
  if (!Array.isArray(bindings) || bindings.length > FILE_INPUT_ARTIFACT_MAX_COUNT) throw new TypeError('file input bindings must be a bounded array');
  const recording = parsedRecording(rawRecording);
  const fileStepIndexes = (recording.steps ?? [])
    .map((step, index) => (isRecordedFileInputStep(step) ? index : null))
    .filter((index) => index !== null);
  const seen = new Set();
  const normalized = [];
  for (const binding of bindings) {
    exactKeys(binding, MATERIALIZED_FIELDS, 'file input binding');
    assertCommonArtifactFields(binding);
    if (seen.has(binding.source_index)) throw new TypeError('duplicate file input source_index');
    seen.add(binding.source_index);
    validateActionIdentity(recording, binding);
    if (typeof binding.path !== 'string' || !binding.path.startsWith('/dev/shm/agent-os-software-tutorial-capture-')) {
      throw new TypeError('file input binding path must be host-materialized tmpfs evidence');
    }
    normalized.push(Object.freeze(structuredClone(binding)));
  }
  if (fileStepIndexes.length !== normalized.length || fileStepIndexes.some((index) => !seen.has(index))) {
    throw new TypeError('every recorded file-input step requires exactly one materialized binding');
  }
  return Object.freeze(normalized);
}

export function fileInputRecordingIdentity(rawRecording) {
  return fingerprintRecording(rawRecording);
}
