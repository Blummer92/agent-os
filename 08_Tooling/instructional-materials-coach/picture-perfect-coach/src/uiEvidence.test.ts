// @vitest-environment node
// Runs in the Node environment so `import.meta.url` is a real file URL and the
// canonical capture module can be loaded for the byte-parity assertions below.
// Nothing here touches the DOM.
import { describe, expect, it } from 'vitest';
import tutorialRecording from './fixtures/tutorial0-recording.json';
import {
  coVisibleIndexes,
  deriveRecordingUiEvidence,
  fingerprintAction,
  frameUiEvidence,
  sha256Hex,
} from './uiEvidence';

const REC_SHA = 'b'.repeat(64);

/**
 * The canonical action-identity digest lives in the capture package
 * (`capture/safe_recording.mjs`, #932). PPUX-F2 will join capture evidence to
 * reviewed steps on that identity, so the browser-side digest must be byte-identical
 * today rather than "close enough" later. The module is loaded dynamically so the
 * cross-package import stays out of the shipped bundle and out of `tsc`'s graph.
 */
const captureModulePromise = import(
  /* @vite-ignore */ new URL('../../capture/safe_recording.mjs', import.meta.url).href
) as Promise<{ fingerprintAction: (step: unknown) => string }>;

describe('SHA-256 known-answer vectors', () => {
  it('matches published digests', () => {
    const encode = (text: string) => new TextEncoder().encode(text);
    expect(sha256Hex(encode(''))).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
    expect(sha256Hex(encode('abc'))).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
    expect(sha256Hex(encode('abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq')))
      .toBe('248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1');
  });

  it('handles multi-block and non-ASCII input', () => {
    const encode = (text: string) => new TextEncoder().encode(text);
    expect(sha256Hex(encode('a'.repeat(1000)))).toHaveLength(64);
    expect(sha256Hex(encode('emoji 🍜 accents éàü'))).toMatch(/^[0-9a-f]{64}$/);
    // Length-extension boundary cases around the 55/56/64-byte padding edges.
    for (const size of [54, 55, 56, 63, 64, 65, 119, 120]) {
      expect(sha256Hex(encode('x'.repeat(size)))).toMatch(/^[0-9a-f]{64}$/);
    }
  });
});

describe('action-identity parity with the capture package', () => {
  it('produces byte-identical digests for every Tutorial 0 recorded step', async () => {
    const capture = await captureModulePromise;
    expect(tutorialRecording.steps.length).toBeGreaterThan(0);
    for (const step of tutorialRecording.steps) {
      expect(fingerprintAction(step)).toBe(capture.fingerprintAction(step));
    }
  });

  it('agrees on canonicalization edge cases', async () => {
    const capture = await captureModulePromise;
    const cases: unknown[] = [
      { type: 'click', selectors: [['aria/Your stuff'], ["[data-testid='x']"]] },
      { zebra: 1, alpha: 2, nested: { z: [3, { y: 'ü' }], a: null } },
      { unicode: 'emoji 🍜 and accents éàü', empty: '', zero: 0, neg: -1, float: 1.5 },
      { deep: { a: { b: { c: { d: [1, 2, { e: true, f: false }] } } } } },
      {},
      [],
    ];
    for (const value of cases) {
      expect(fingerprintAction(value)).toBe(capture.fingerprintAction(value));
    }
  });

  it('is insensitive to key order but sensitive to value change', async () => {
    const capture = await captureModulePromise;
    const a = { alpha: 1, beta: 2 };
    const b = { beta: 2, alpha: 1 };
    expect(fingerprintAction(a)).toBe(fingerprintAction(b));
    expect(capture.fingerprintAction(a)).toBe(fingerprintAction(b));
    expect(fingerprintAction({ alpha: 1, beta: 3 })).not.toBe(fingerprintAction(a));
  });
});

describe('recording UI-claim derivation', () => {
  const evidence = deriveRecordingUiEvidence(tutorialRecording, REC_SHA);

  it('derives accessible names and entered values, and nothing else', () => {
    const kinds = new Set(evidence.claims.map((claim) => claim.kind));
    expect([...kinds].sort()).toEqual(['accessible-name', 'entered-value']);
    const texts = new Set(evidence.claims.map((claim) => claim.text));
    expect(texts.has('Create new')).toBe(true);        // aria at index 13
    expect(texts.has('Digital Media')).toBe(true);     // entered value at index 4
    expect(texts.has('Create new file')).toBe(false);  // never recorded
    expect(texts.has('Square project')).toBe(false);   // semantic target, not UI text
    expect(texts.has('Tutorial 0 folder')).toBe(false);
  });

  it('binds every claim to its own source state and action identity', () => {
    const identityByIndex = new Map(evidence.actionIdentity.map((item) => [item.sourceIndex, item.sourceFingerprint]));
    for (const claim of evidence.claims) {
      expect(claim.recordingSha256).toBe(REC_SHA);
      expect(identityByIndex.get(claim.sourceIndex)).toBe(claim.sourceFingerprint);
    }
  });

  it('records action identity for every recorded step', () => {
    expect(evidence.actionIdentity).toHaveLength(tutorialRecording.steps.length);
    expect(new Set(evidence.actionIdentity.map((item) => item.sourceIndex)).size).toBe(tutorialRecording.steps.length);
  });

  it('locates the known Tutorial 0 states precisely', () => {
    const at = (text: string) => evidence.claims.filter((claim) => claim.text === text).map((claim) => claim.sourceIndex);
    expect(at('Tutorial 0 - Organize My Files')).toEqual([9]);
    expect(at('Square')).toEqual([14]);
    expect(at('Landscape')).toEqual([20]);
    expect(at('Portrait')).toEqual([26]);
  });
});

describe('frame narrowing and co-visibility', () => {
  const evidence = deriveRecordingUiEvidence(tutorialRecording, REC_SHA);

  it('withholds claims outside the frame source indexes', () => {
    const frame = frameUiEvidence(evidence, [13, 14]);
    const local = new Set(frame.stateLocalClaims.map((claim) => claim.text));
    expect(local.has('Create new')).toBe(true);
    expect(local.has('Square')).toBe(true);
    expect(local.has('Portrait')).toBe(false);
    // Whole-recording texts stay visible so escape-hatch detection still works.
    expect(frame.recordingClaimTexts).toContain('Portrait');
  });

  it('reports no shared state for details observed apart', () => {
    const frame = frameUiEvidence(evidence, [14, 20, 26]);
    expect(coVisibleIndexes(frame.stateLocalClaims, ['Square', 'Landscape', 'Portrait'])).toEqual([]);
  });

  it('reports the shared state when one step observed both details', () => {
    const both = deriveRecordingUiEvidence(
      { steps: [{ type: 'click', selectors: [['aria/One'], ['aria/Two']] }] },
      REC_SHA,
    );
    expect(coVisibleIndexes(both.claims, ['One', 'Two'])).toEqual([0]);
  });

  it('treats an empty request list as establishing nothing', () => {
    expect(coVisibleIndexes(evidence.claims, [])).toEqual([]);
  });
});
