/**
 * PPUX-F1 (#1293) — provenance-bound UI-claim evidence.
 *
 * Literal UI evidence exists only in the raw Recorder recording, in two distinct
 * kinds: accessible names exposed by the interface (`aria/...` selectors) and
 * values the teacher typed (`change.value`). Semantic modeling fields such as a
 * candidate `target` are instructional descriptors, not observed UI text, and are
 * never a source of UI claims here.
 *
 * Every claim is bound to the exact source state it was observed at
 * (`sourceIndex`) and to that action's identity (`sourceFingerprint`), so a claim
 * can never silently authorize a different action or a different recording.
 */

/** How a UI text was evidenced at its source state. */
export type UiEvidenceKind = 'accessible-name' | 'entered-value';

/** One state-local UI text observation bound to one action identity. */
export interface UiClaim {
  readonly text: string;
  readonly kind: UiEvidenceKind;
  readonly sourceIndex: number;
  readonly sourceFingerprint: string;
  readonly recordingSha256: string;
}

/**
 * Action identity for one recorded step. `sourceIndex` alone is array position and
 * is never sufficient; `sourceFingerprint` detects a recording edit that shifts or
 * replaces an action. PPUX-F2 joins capture evidence on both together.
 */
export interface ActionIdentity {
  readonly sourceIndex: number;
  readonly sourceFingerprint: string;
}

/** Derived UI evidence for one whole recording. */
export interface RecordingUiEvidence {
  readonly recordingSha256: string;
  readonly actionIdentity: readonly ActionIdentity[];
  readonly claims: readonly UiClaim[];
}

/** Bounded UI evidence visible to one Stage-4 frame. */
export interface FrameUiEvidence {
  readonly sourceIndexes: readonly number[];
  /** Action identity for this frame's own source indexes only. */
  readonly actionIdentity: readonly ActionIdentity[];
  /** Claims observed at this frame's own source indexes only. */
  readonly stateLocalClaims: readonly UiClaim[];
  /** Every UI text observed anywhere in the recording, for escape-hatch detection. */
  readonly recordingClaimTexts: readonly string[];
}

const ARIA_PREFIX = 'aria/';

const SHA256_K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function rotr(value: number, bits: number): number {
  return ((value >>> bits) | (value << (32 - bits))) >>> 0;
}

/**
 * Synchronous SHA-256 over raw bytes.
 *
 * The browser has no synchronous digest (`crypto.subtle` is async) and `node:crypto`
 * is not available in this surface, so the digest is computed here to keep the whole
 * PPUX evidence pipeline synchronous. Output is byte-identical to the capture
 * package's `node:crypto` digest for the same input; `uiEvidence.test.ts` proves that
 * against `capture/safe_recording.mjs` directly.
 */
export function sha256Hex(bytes: Uint8Array): string {
  const length = bytes.length;
  const padded = new Uint8Array((((length + 9 + 63) / 64) | 0) * 64);
  padded.set(bytes);
  padded[length] = 0x80;
  const view = new DataView(padded.buffer);
  const bitLength = length * 8;
  view.setUint32(padded.length - 8, Math.floor(bitLength / 0x100000000));
  view.setUint32(padded.length - 4, bitLength >>> 0);

  const state = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  const schedule = new Uint32Array(64);

  for (let offset = 0; offset < padded.length; offset += 64) {
    for (let t = 0; t < 16; t += 1) schedule[t] = view.getUint32(offset + t * 4);
    for (let t = 16; t < 64; t += 1) {
      const w15 = schedule[t - 15];
      const w2 = schedule[t - 2];
      const s0 = rotr(w15, 7) ^ rotr(w15, 18) ^ (w15 >>> 3);
      const s1 = rotr(w2, 17) ^ rotr(w2, 19) ^ (w2 >>> 10);
      schedule[t] = (schedule[t - 16] + s0 + schedule[t - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = state;
    for (let t = 0; t < 64; t += 1) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const choose = (e & f) ^ (~e & g);
      const temp1 = (h + S1 + choose + SHA256_K[t] + schedule[t]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (S0 + majority) >>> 0;
      h = g; g = f; f = e; e = (d + temp1) >>> 0;
      d = c; c = b; b = a; a = (temp1 + temp2) >>> 0;
    }
    state[0] = (state[0] + a) >>> 0; state[1] = (state[1] + b) >>> 0;
    state[2] = (state[2] + c) >>> 0; state[3] = (state[3] + d) >>> 0;
    state[4] = (state[4] + e) >>> 0; state[5] = (state[5] + f) >>> 0;
    state[6] = (state[6] + g) >>> 0; state[7] = (state[7] + h) >>> 0;
  }

  let hex = '';
  for (let i = 0; i < 8; i += 1) hex += state[i].toString(16).padStart(8, '0');
  return hex;
}

/**
 * Deep key-sorted normalization. Must stay behaviourally identical to `canonicalize`
 * in `capture/safe_recording.mjs`; the parity test locks that.
 */
function canonicalizeAction(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalizeAction);
  if (value !== null && typeof value === 'object') {
    const result: Record<string, unknown> = {};
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      result[key] = canonicalizeAction((value as Record<string, unknown>)[key]);
    }
    return result;
  }
  return value;
}

/**
 * Action identity digest for one recorded step.
 *
 * Byte-compatible with `fingerprintAction` in
 * `08_Tooling/instructional-materials-coach/capture/safe_recording.mjs`.
 */
export function fingerprintAction(step: unknown): string {
  return sha256Hex(new TextEncoder().encode(JSON.stringify(canonicalizeAction(step))));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Accessible names exposed by one recorded step's selector alternatives. */
function accessibleNames(step: Record<string, unknown>): string[] {
  if (!Array.isArray(step.selectors)) return [];
  const names: string[] = [];
  for (const group of step.selectors) {
    if (!Array.isArray(group)) continue;
    for (const selector of group) {
      if (typeof selector === 'string' && selector.startsWith(ARIA_PREFIX)) {
        const text = selector.slice(ARIA_PREFIX.length).trim();
        if (text.length > 0) names.push(text);
      }
    }
  }
  return names;
}

/**
 * Derive every UI claim and action identity in one recording.
 *
 * Claims come only from observed accessible names and entered values. Nothing here
 * reads modeling candidates, step titles, student-action text, branding, or the
 * tutorial name.
 */
export function deriveRecordingUiEvidence(recording: unknown, recordingSha256: string): RecordingUiEvidence {
  const claims: UiClaim[] = [];
  const actionIdentity: ActionIdentity[] = [];
  const steps = isRecord(recording) && Array.isArray(recording.steps) ? recording.steps : [];

  for (let sourceIndex = 0; sourceIndex < steps.length; sourceIndex += 1) {
    const step = steps[sourceIndex];
    if (!isRecord(step)) continue;
    const sourceFingerprint = fingerprintAction(step);
    actionIdentity.push({ sourceIndex, sourceFingerprint });

    for (const text of accessibleNames(step)) {
      claims.push({ text, kind: 'accessible-name', sourceIndex, sourceFingerprint, recordingSha256 });
    }
    if (step.type === 'change' && typeof step.value === 'string' && step.value.trim().length > 0) {
      claims.push({
        text: step.value,
        kind: 'entered-value',
        sourceIndex,
        sourceFingerprint,
        recordingSha256,
      });
    }
  }

  return {
    recordingSha256,
    actionIdentity,
    claims,
  };
}

/**
 * Narrow whole-recording evidence to the bounded evidence one frame may rely on.
 * Claims outside `sourceIndexes` are withheld, which is what makes evidence
 * state-local rather than tutorial-global.
 */
export function frameUiEvidence(
  evidence: RecordingUiEvidence,
  sourceIndexes: readonly number[],
): FrameUiEvidence {
  const scope = new Set(sourceIndexes);
  return {
    sourceIndexes: [...sourceIndexes],
    actionIdentity: evidence.actionIdentity.filter((item) => scope.has(item.sourceIndex)),
    stateLocalClaims: evidence.claims.filter((claim) => scope.has(claim.sourceIndex)),
    recordingClaimTexts: [...new Set(evidence.claims.map((claim) => claim.text))],
  };
}

/**
 * Source indexes at which every requested text was observed together.
 *
 * Co-visibility is a capture-evidence question: two texts observed at different
 * source states are not proven to appear on one screen. An empty result means the
 * recording does not establish co-visibility.
 */
export function coVisibleIndexes(
  claims: readonly UiClaim[],
  requestedTexts: readonly string[],
): number[] {
  if (requestedTexts.length === 0) return [];
  const byIndex = new Map<number, Set<string>>();
  for (const claim of claims) {
    const existing = byIndex.get(claim.sourceIndex) ?? new Set<string>();
    existing.add(claim.text);
    byIndex.set(claim.sourceIndex, existing);
  }
  const shared: number[] = [];
  for (const [sourceIndex, texts] of byIndex) {
    if (requestedTexts.every((text) => texts.has(text))) shared.push(sourceIndex);
  }
  return shared.sort((left, right) => left - right);
}
