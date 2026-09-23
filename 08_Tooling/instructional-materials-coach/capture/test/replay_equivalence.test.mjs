import assert from 'node:assert/strict';
import test from 'node:test';

import {
  compareReplayEvidence,
  RJ4_FIXTURE_VERSION,
  RJ4_STATUSES,
  runSyntheticReplay,
  validateReplayEquivalence,
} from '../replay_equivalence.mjs';

const flow = (title, steps) => JSON.stringify({ title, steps });
const click = testid => ({ type: 'click', selectors: [[`[data-testid="${testid}"]`]], offsetX: 2, offsetY: 2 });
const doubleClick = testid => ({ type: 'doubleClick', selectors: [[`[data-testid="${testid}"]`]], offsetX: 2, offsetY: 2 });
const change = (testid, value) => ({ type: 'change', selectors: [[`[data-testid="${testid}"]`]], value });
const key = (type, value) => ({ type, key: value });
const waitVisible = testid => ({ type: 'waitForElement', selectors: [[`[data-testid="${testid}"]`]], visible: true });

const state = (overrides = {}) => ({ folder: 'Folder A', title: 'Assignment 1', mode: 'idle', modal: 'closed', error: '', recovered: false, ready: false, ...overrides });
const passed = (checkpoints, finalState) => ({ status: 'passed', checkpoints, final_state: finalState });

function evidenceRunner(map) {
  return async raw => {
    const { title } = JSON.parse(raw);
    return map[title];
  };
}

test('exports the finite RJ4 result vocabulary', () => {
  assert.deepEqual(RJ4_STATUSES, ['equivalent', 'not-equivalent', 'indeterminate', 'runner-unavailable']);
  assert.equal(RJ4_FIXTURE_VERSION, 'rj4-synthetic-fixture-v1');
});

test('comparison proves observable equivalence rather than step-count equality', () => {
  const checkpoint = state({ mode: 'selected:Folder A' });
  const original = passed([state(), checkpoint], checkpoint);
  const candidate = passed([state(), checkpoint], checkpoint);
  assert.deepEqual(compareReplayEvidence(original, candidate), {
    status: 'equivalent', behaviorally_safe: true, reason_code: null,
  });
});

test('observable mismatch fails equivalence', () => {
  const original = passed([state({ mode: 'selected:Folder A' })], state({ mode: 'selected:Folder A' }));
  const candidate = passed([state({ mode: 'selected:Folder B' })], state({ mode: 'selected:Folder B' }));
  assert.equal(compareReplayEvidence(original, candidate).status, 'not-equivalent');
});

test('indeterminate and runner-unavailable fail closed', () => {
  assert.deepEqual(compareReplayEvidence({ status: 'indeterminate' }, passed([], state())), {
    status: 'indeterminate', behaviorally_safe: false, reason_code: 'rj4-indeterminate',
  });
  assert.deepEqual(compareReplayEvidence({ status: 'runner-unavailable' }, passed([], state())), {
    status: 'runner-unavailable', behaviorally_safe: false, reason_code: 'rj4-runner-unavailable',
  });
});

const unchangedOriginal = flow('unchanged-original', [click('folder')]);
const unchangedCandidate = flow('unchanged-candidate', [click('folder')]);
const keyboardNoiseOriginal = flow('keyboard-noise-original', [change('title-input', 'Assignment'), key('keyDown', 'Backspace'), key('keyUp', 'Backspace'), change('title-input', 'Assignment 1')]);
const keyboardNoiseCandidate = flow('keyboard-noise-candidate', [change('title-input', 'Assignment 1')]);
const duplicateOriginal = flow('duplicate-original', [click('folder'), click('folder')]);
const duplicateCandidate = flow('duplicate-candidate', [click('folder')]);
const safeReorderOriginal = flow('safe-reorder-original', [click('folder'), change('title-input', 'Student A')]);
const safeReorderCandidate = flow('safe-reorder-candidate', [change('title-input', 'Student A'), click('folder')]);
const unsafeReorderOriginal = flow('unsafe-reorder-original', [click('step-one'), click('step-two')]);
const unsafeReorderCandidate = flow('unsafe-reorder-candidate', [click('step-two'), click('step-one')]);
const clickOriginal = flow('click-original', [click('folder')]);
const doubleClickCandidate = flow('double-click-candidate', [doubleClick('folder')]);
const recoveryOriginal = flow('recovery-original', [click('cause-error'), click('recover')]);
const recoveryCandidate = flow('recovery-candidate', [click('cause-error')]);
const loadingOriginal = flow('loading-original', [click('start-loading'), waitVisible('ready')]);
const loadingCandidate = flow('loading-candidate', [click('start-loading')]);
const selectorOriginal = flow('selector-original', [click('folder')]);
const selectorEquivalent = flow('selector-equivalent', [click('equivalent-folder')]);
const selectorWrong = flow('selector-wrong', [click('wrong-folder')]);
const timeoutOriginal = flow('timeout-original', [click('folder')]);
const timeoutCandidate = flow('timeout-candidate', [waitVisible('never-exists')]);

const A = state({ mode: 'selected:Folder A' });
const B = state({ mode: 'selected:Folder B' });
const ordered = state({ mode: 'ordered-complete' });
const orderError = state({ mode: 'step-one' });
const opened = state({ mode: 'opened:Folder A' });
const recovered = state({ recovered: true });
const errored = state({ error: 'recoverable' });
const titled = state({ title: 'Student A', mode: 'selected:Folder A' });
const ready = state({ ready: true });

const matrixEvidence = {
  'unchanged-original': passed([A], A),
  'unchanged-candidate': passed([A], A),
  'keyboard-noise-original': passed([state({ title: 'Assignment' }), state()], state()),
  'keyboard-noise-candidate': passed([state()], state()),
  'duplicate-original': passed([A], A),
  'duplicate-candidate': passed([A], A),
  'safe-reorder-original': passed([titled], titled),
  'safe-reorder-candidate': passed([titled], titled),
  'unsafe-reorder-original': passed([state({ mode: 'step-one' }), ordered], ordered),
  'unsafe-reorder-candidate': passed([state({ mode: 'order-error' }), orderError], orderError),
  'click-original': passed([A], A),
  'double-click-candidate': passed([opened], opened),
  'recovery-original': passed([errored, recovered], recovered),
  'recovery-candidate': passed([errored], errored),
  'loading-original': passed([state({ ready: false }), ready], ready),
  'loading-candidate': passed([ready], ready),
  'selector-original': passed([A], A),
  'selector-equivalent': passed([A], A),
  'selector-wrong': passed([B], B),
  'timeout-original': passed([A], A),
  'timeout-candidate': { status: 'indeterminate', checkpoints: [], final_state: null },
};

for (const [name, original, candidate, expected] of [
  ['unchanged rewrite', unchangedOriginal, unchangedCandidate, 'equivalent'],
  ['keyboard-noise collapse', keyboardNoiseOriginal, keyboardNoiseCandidate, 'equivalent'],
  ['duplicate-noise removal', duplicateOriginal, duplicateCandidate, 'equivalent'],
  ['safe reorder', safeReorderOriginal, safeReorderCandidate, 'equivalent'],
  ['unsafe reorder', unsafeReorderOriginal, unsafeReorderCandidate, 'not-equivalent'],
  ['click to doubleClick mutation', clickOriginal, doubleClickCandidate, 'not-equivalent'],
  ['required recovery removal', recoveryOriginal, recoveryCandidate, 'not-equivalent'],
  ['unnecessary loading noise removal', loadingOriginal, loadingCandidate, 'equivalent'],
  ['equivalent selector replacement', selectorOriginal, selectorEquivalent, 'equivalent'],
  ['wrong selector replacement', selectorOriginal, selectorWrong, 'not-equivalent'],
  ['timeout ambiguity', timeoutOriginal, timeoutCandidate, 'indeterminate'],
]) test(`required pair: ${name}`, async () => {
  const result = await validateReplayEquivalence(original, candidate, { runReplay: evidenceRunner(matrixEvidence) });
  assert.equal(result.status, expected);
  assert.equal(result.external_write_authorized, false);
  assert.equal(result.production_authorized, false);
  assert.match(result.fixture_sha256, /^[0-9a-f]{64}$/);
  assert.match(result.original_sha256, /^[0-9a-f]{64}$/);
  assert.match(result.candidate_sha256, /^[0-9a-f]{64}$/);
});

test('RJ3-invalid candidate is rejected before replay', async () => {
  let replayCalls = 0;
  const result = await validateReplayEquivalence(unchangedOriginal, '{"title":"bad"}', {
    runReplay: async () => { replayCalls += 1; return passed([], state()); },
  });
  assert.equal(result.status, 'not-equivalent');
  assert.equal(result.reason_code, 'rj4-rj3-conformance-required');
  assert.equal(replayCalls, 0);
});

test('same evidence produces deterministic normalized result', async () => {
  const options = { runReplay: evidenceRunner(matrixEvidence) };
  assert.deepEqual(
    await validateReplayEquivalence(unchangedOriginal, unchangedCandidate, options),
    await validateReplayEquivalence(unchangedOriginal, unchangedCandidate, options),
  );
});

test('real pinned Replay smoke executes a known-valid synthetic flow locally', async () => {
  const result = await runSyntheticReplay(flow('smoke', [click('folder')]));
  if (result.status === 'runner-unavailable') {
    assert.equal(result.failure.reason_code, 'rj4-runner-unavailable');
    return;
  }
  assert.equal(result.status, 'passed');
  assert.equal(result.replay_version, '4.0.2');
  assert.equal(result.final_state.mode, 'selected:Folder A');
});
