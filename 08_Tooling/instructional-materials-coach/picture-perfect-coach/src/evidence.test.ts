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
});