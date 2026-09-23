import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { SUPPORTED_REPLAY_VERSION, validateRecorderConformance } from '../recorder_conformance.mjs';

function flow(steps, extra = {}) { return JSON.stringify({ title: 'Synthetic Recorder flow', steps, ...extra }); }
const click = { type: 'click', selectors: [['aria/Create']], offsetX: 4, offsetY: 5 };
const doubleClick = { type: 'doubleClick', selectors: [['aria/Open']], offsetX: 4, offsetY: 5 };
const change = { type: 'change', selectors: [['aria/Name']], value: 'Folder A' };
const keyPair = [{ type: 'keyDown', key: 'Enter' }, { type: 'keyUp', key: 'Enter' }];
const waitForElement = { type: 'waitForElement', selectors: [['aria/Ready']], visible: true };
const validate = (raw, options = {}) => validateRecorderConformance(raw, options);

for (const [name, steps] of [
  ['minimal navigation', [{ type: 'navigate', url: 'https://example.test/' }]], ['click selector chain', [click]],
  ['doubleClick selector chain', [doubleClick]], ['change text entry', [change]], ['keyDown/keyUp', keyPair],
  ['waitForElement assertion-capable flow', [waitForElement]],
]) test(`accepts valid ${name}`, async () => {
  const result = await validate(flow(steps));
  assert.equal(result.status, 'recorder-valid');
  assert.equal(result.validator.version, SUPPORTED_REPLAY_VERSION);
  assert.equal(result.behavioral_equivalence_proven, false);
  assert.deepEqual(result.diagnostic_codes, []);
});

test('accepts representative RJ2 clean and noisy rewritten fixtures', async () => {
  for (const name of ['rj2-clean-rewrite.json', 'rj2-noisy-rewrite.json']) {
    const result = await validate(await readFile(new URL(`./fixtures/${name}`, import.meta.url)));
    assert.equal(result.status, 'recorder-valid');
  }
});

test('reports malformed JSON separately', async () => {
  const result = await validate('{"title":');
  assert.equal(result.status, 'json-invalid');
  assert.deepEqual(result.diagnostic_codes, ['json-parse-invalid']);
});

for (const [name, value] of [
  ['missing steps', { title: 'x' }], ['steps not array', { title: 'x', steps: {} }],
  ['step missing type', { title: 'x', steps: [{}] }], ['malformed selectors', { title: 'x', steps: [{ ...click, selectors: {} }] }],
  ['broken nested selector arrays', { title: 'x', steps: [{ ...click, selectors: [[123]] }] }],
  ['missing navigation URL', { title: 'x', steps: [{ type: 'navigate' }] }],
  ['missing change value', { title: 'x', steps: [{ type: 'change', selectors: [['aria/Name']] }] }],
  ['invalid numeric field type', { title: 'x', steps: [{ ...click, offsetX: '4' }] }],
  ['malformed rewritten output', { title: 'x', steps: [{ type: 'click', selectors: [['aria/Create']], offsetX: 1 }] }],
  ['top-level array', []],
]) test(`rejects ${name} with stable bounded diagnostics`, async () => {
  const result = await validate(JSON.stringify(value));
  assert.equal(result.status, 'recorder-invalid');
  assert.deepEqual(result.diagnostic_codes, ['recorder-format-invalid']);
});

test('normalizes upstream rejection without leaking exception text', async () => {
  const secret = '/private/path/token=synthetic-secret';
  const result = await validate(flow([click]), { loadReplay: async () => ({ parse() { throw new Error(secret); } }), resolveValidatorVersion: () => SUPPORTED_REPLAY_VERSION });
  assert.equal(result.status, 'recorder-invalid');
  assert.equal(JSON.stringify(result).includes(secret), false);
});

test('documents upstream acceptance of unknown extension fields', async () => {
  assert.equal((await validate(flow([{ ...click, extensionPayload: true }], { extensionTopLevel: true }))).status, 'recorder-valid');
});

test('validator unavailability fails closed', async () => {
  const result = await validate(flow([click]), { loadReplay: async () => { throw new Error('/private/path'); } });
  assert.equal(result.status, 'validator-unavailable');
  assert.equal(JSON.stringify(result).includes('/private/path'), false);
});

test('invalid validator API is distinct', async () => assert.equal((await validate(flow([click]), { loadReplay: async () => ({}) })).status, 'validator-error'));
test('validator version lookup failure is bounded', async () => {
  const result = await validate(flow([click]), { loadReplay: async () => ({ parse() {} }), resolveValidatorVersion: () => { throw new Error('/private/path'); } });
  assert.deepEqual(result.diagnostic_codes, ['validator-version-unavailable']);
});
test('version drift fails closed', async () => {
  const result = await validate(flow([click]), { loadReplay: async () => ({ parse() {} }), resolveValidatorVersion: () => '9.9.9' });
  assert.deepEqual(result.diagnostic_codes, ['validator-version-mismatch']);
});
test('same input produces deterministic evidence', async () => {
  const raw = flow([click, change]);
  assert.deepEqual(await validate(raw), await validate(raw));
});
