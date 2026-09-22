import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';

import {
  fileInputArtifactIdentity,
  isRecordedFileInputStep,
  validateFileInputArtifacts,
} from '../file_input_bindings.mjs';
import { fingerprintAction } from '../safe_recording.mjs';

function recording(stepOverrides = {}) {
  const step = {
    type: 'change',
    selectors: [['#file']],
    value: 'C:\\fakepath\\practice.pdf',
    ...stepOverrides,
  };
  return {
    raw: JSON.stringify({ title: 'synthetic', steps: [step] }),
    step,
  };
}

function artifactFor(step, bytes = Buffer.from('synthetic pdf bytes'), overrides = {}) {
  return {
    source_index: 0,
    source_fingerprint: fingerprintAction(step),
    content_ref: 'capture-inputs/practice.pdf',
    sha256: createHash('sha256').update(bytes).digest('hex'),
    filename: 'practice.pdf',
    content_base64: bytes.toString('base64'),
    ...overrides,
  };
}

test('detects Recorder fakepath file-input values without classifying normal text changes', () => {
  assert.equal(isRecordedFileInputStep(recording().step), true);
  assert.equal(isRecordedFileInputStep({ type: 'change', value: 'hello' }), false);
});

test('valid artifact is bound to the exact recording action and digest', () => {
  const { raw, step } = recording();
  const result = validateFileInputArtifacts(raw, [artifactFor(step)]);
  assert.equal(result.length, 1);
  assert.deepEqual(fileInputArtifactIdentity(result[0]), {
    source_index: 0,
    source_fingerprint: fingerprintAction(step),
    content_ref: 'capture-inputs/practice.pdf',
    sha256: artifactFor(step).sha256,
    filename: 'practice.pdf',
  });
});

test('missing artifact for a recorded file-input step fails closed', () => {
  const { raw } = recording();
  assert.throws(() => validateFileInputArtifacts(raw, []), /requires exactly one bounded artifact/);
});

test('action fingerprint mismatch and digest mismatch fail closed', () => {
  const { raw, step } = recording();
  assert.throws(
    () => validateFileInputArtifacts(raw, [artifactFor(step, undefined, { source_fingerprint: '0'.repeat(64) })]),
    /source fingerprint mismatch/,
  );
  assert.throws(
    () => validateFileInputArtifacts(raw, [artifactFor(step, undefined, { sha256: '0'.repeat(64) })]),
    /digest mismatch/,
  );
});

test('caller paths and unknown artifact fields are unrepresentable', () => {
  const { raw, step } = recording();
  const artifact = artifactFor(step);
  assert.throws(() => validateFileInputArtifacts(raw, [{ ...artifact, path: '/tmp/private.pdf' }]), /unsupported/);
  assert.throws(() => validateFileInputArtifacts(raw, [{ ...artifact, profile_path: '/tmp/profile' }]), /unsupported/);
});

test('ordinary no-file recordings remain compatible with an empty artifact set', () => {
  const raw = JSON.stringify({
    title: 'synthetic',
    steps: [{ type: 'change', selectors: [['#name']], value: 'student' }],
  });
  assert.deepEqual(validateFileInputArtifacts(raw, []), []);
});
