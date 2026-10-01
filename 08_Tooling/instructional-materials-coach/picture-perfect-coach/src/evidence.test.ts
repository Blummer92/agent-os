import tutorialEvidence from './fixtures/tutorial0-evidence.json';
import tutorialRecording from './fixtures/tutorial0-recording.json';
import { safeTechnicalDetails, summarizeEvidence, validateUploadText } from './evidence';
import { deriveRecordingUiEvidence } from './uiEvidence';
import type { UploadEvidenceProjection } from './types';

describe('upload evidence consumer', () => {
  const projected = tutorialEvidence as unknown as Omit<UploadEvidenceProjection, 'recording_evidence'>;
  const evidence: UploadEvidenceProjection = {
    ...projected,
    recording_evidence: deriveRecordingUiEvidence(tutorialRecording, projected.recording_sha256),
  };

  it('derives summary counts instead of storing presentation totals', () => {
    const summary = summarizeEvidence(evidence);
    expect(summary.actionsFound).toBe(evidence.modeling_candidates.length);
    expect(summary.instructionalCandidates).toBe(
      evidence.modeling_steps.filter((step) => ['keep', 'combine', 'needs-review'].includes(step.disposition)).length,
    );
    expect(summary.needsReview).toBe(evidence.modeling_steps.filter((step) => step.disposition === 'needs-review').length);
  });

  it('sanitizes technical disclosure to provenance-safe fields', () => {
    const technical = safeTechnicalDetails(evidence);
    const serialized = JSON.stringify(technical);
    expect(serialized).not.toContain('selectors');
    expect(serialized).not.toContain('new.express.adobe.test');
    expect(serialized).not.toContain('synthetic-food-bowl.jpg');
    expect(serialized).not.toContain('target');
  });

  it('accepts the exact synthetic fixture with authority-false evidence', () => {
    const result = validateUploadText(JSON.stringify(tutorialRecording));
    expect(result.ok).toBe(true);
    expect(evidence.modeling_candidates.every((item) => item.execution_authorized === false)).toBe(true);
    expect(evidence.modeling_steps.every((item) => item.execution_authorized === false)).toBe(true);
  });

  it('surfaces off-approved-origin navigation and fails closed', () => {
    const unsafe = structuredClone(tutorialRecording);
    const navigate = unsafe.steps.find((step) => step.type === 'navigate');
    if (!navigate || navigate.type !== 'navigate') throw new Error('fixture navigate step missing');
    navigate.url = 'https://example.invalid/not-approved';
    const result = validateUploadText(JSON.stringify(unsafe));
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('unsafe recording unexpectedly accepted');
    expect(result.message).toMatch(/outside the approved Adobe Express modeling origin/i);
  });

  it.each([
    ['https://express.adobe.com/your-stuff/files', 'https://express.adobe.com'],
    ['https://new.express.adobe.com/your-stuff/files', 'https://new.express.adobe.com'],
  ])('accepts a real Adobe Express origin (%s) through the origin gate', (url) => {
    const real = structuredClone(tutorialRecording);
    let rewrote = 0;
    for (const step of real.steps) {
      if (step.type === 'navigate' && typeof (step as { url?: unknown }).url === 'string') {
        (step as { url: string }).url = url;
        rewrote += 1;
      }
    }
    if (rewrote === 0) throw new Error('fixture navigate step missing');
    const result = validateUploadText(JSON.stringify(real));
    // The origin gate must pass; the recording then fails only on the
    // canonical-evidence check (no Teacher Modeling evidence exists for this
    // synthetic real-origin recording yet), proving the origin itself was accepted.
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('expected canonical-evidence rejection');
    expect(result.message).not.toMatch(/outside the approved Adobe Express modeling origin/i);
    expect(result.message).toMatch(/no Teacher Modeling evidence/i);
  });

  it('rejects the synthetic test origin in production mode', () => {
    // No bare `process` reference: this Vite package does not bundle node
    // types. Reaches Node's env the same way src/evidence.ts does.
    const nodeProcess = (globalThis as { process?: { env: Record<string, string | undefined> } }).process;
    if (!nodeProcess?.env) throw new Error('process.env unavailable in this test environment');
    const savedNodeEnv = nodeProcess.env['NODE_ENV'];
    const savedVitest = nodeProcess.env['VITEST'];
    delete nodeProcess.env['VITEST'];
    nodeProcess.env['NODE_ENV'] = 'production';
    try {
      const result = validateUploadText(JSON.stringify(tutorialRecording));
      expect(result.ok).toBe(false);
      if (result.ok) throw new Error('synthetic origin unexpectedly accepted in production mode');
      expect(result.message).toMatch(/outside the approved Adobe Express modeling origin/i);
    } finally {
      if (savedVitest === undefined) delete nodeProcess.env['VITEST'];
      else nodeProcess.env['VITEST'] = savedVitest;
      if (savedNodeEnv === undefined) delete nodeProcess.env['NODE_ENV'];
      else nodeProcess.env['NODE_ENV'] = savedNodeEnv;
    }
  });
});