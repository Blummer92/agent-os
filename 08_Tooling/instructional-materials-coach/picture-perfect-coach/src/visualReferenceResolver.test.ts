import { describe, expect, it, vi } from 'vitest';
import type { ApprovedVisualReference } from './visualReference';
import {
  VISUAL_REFERENCE_RESOLUTION_REASONS,
  resolveVisualReferencePresentationInput,
  type DriveImageIdentity,
  type ExactDriveImageReader,
} from './visualReferenceResolver';

const reference: ApprovedVisualReference = {
  reference_id: 'adobe-editor-add-content',
  application: 'Adobe Express',
  application_variant: 'Education',
  context_state: 'editor/add-content',
  captured_at: '2026-08-24T14:57:20Z',
  verified_at: '2026-08-24T15:00:00Z',
  sanitized_derivative_reference: 'sanitized://editor-add-content',
  source_reference: 'teacher-upload://editor-add-content',
  provenance: ['PPUX fixture', 'source-state:editor/add-content'],
  visible_ui_claims: ['Adobe Express', 'Add content', 'Media'],
  manifest_reference: {
    manifest_id: 'manifest-adobe-current-ui',
    record_revision: 1,
    fingerprint: 'manifest-fingerprint',
    verified_at: '2026-08-24T15:00:00Z',
    external_file_id: 'drive-file-exact-123',
  },
  asset_reference: {
    asset_id: 'asset-editor-add-content',
    stable_ref: 'visual-reference://editor-add-content',
    content_fingerprint: 'sha256:approved-image',
  },
};

const observed: DriveImageIdentity = {
  file_id: 'drive-file-exact-123',
  mime_type: 'image/png',
  stable_ref: 'visual-reference://editor-add-content',
  content_fingerprint: 'sha256:approved-image',
  current: true,
};

function reader(value: DriveImageIdentity | null = observed): ExactDriveImageReader & { readExactImage: ReturnType<typeof vi.fn> } {
  return { readExactImage: vi.fn().mockResolvedValue(value) };
}

describe('PPUX-VRL5 exact Drive-backed visual reference resolution', () => {
  it('resolves one approved reference to one exact presentation input and preserves identity', async () => {
    const exactReader = reader();
    const result = await resolveVisualReferencePresentationInput(reference, exactReader);

    expect(result.status).toBe('valid');
    expect(exactReader.readExactImage).toHaveBeenCalledTimes(1);
    expect(exactReader.readExactImage).toHaveBeenCalledWith('drive-file-exact-123');
    expect(result.input).toMatchObject({
      reference_id: reference.reference_id,
      context_state: 'editor/add-content',
      manifest_id: 'manifest-adobe-current-ui',
      external_file_id: 'drive-file-exact-123',
      asset_id: 'asset-editor-add-content',
      stable_ref: 'visual-reference://editor-add-content',
      content_fingerprint: 'sha256:approved-image',
      mime_type: 'image/png',
      source_reference: reference.source_reference,
      sanitized_derivative_reference: reference.sanitized_derivative_reference,
    });
    expect(result.input?.provenance).toEqual(reference.provenance);
    expect(result.input?.visible_ui_claims).toEqual(reference.visible_ui_claims);
  });

  it.each([
    ['external file ID', { ...observed, file_id: 'wrong-id' }, VISUAL_REFERENCE_RESOLUTION_REASONS.externalFileIdMismatch, 'blocked'],
    ['stable asset identity', { ...observed, stable_ref: 'visual-reference://other' }, VISUAL_REFERENCE_RESOLUTION_REASONS.stableReferenceMismatch, 'blocked'],
    ['content fingerprint', { ...observed, content_fingerprint: 'sha256:old' }, VISUAL_REFERENCE_RESOLUTION_REASONS.contentFingerprintMismatch, 'stale'],
    ['MIME type', { ...observed, mime_type: 'application/pdf' }, VISUAL_REFERENCE_RESOLUTION_REASONS.wrongMimeType, 'blocked'],
    ['currentness', { ...observed, current: false }, VISUAL_REFERENCE_RESOLUTION_REASONS.stale, 'stale'],
  ] as const)('fails closed on %s mismatch', async (_label, value, reason, status) => {
    const result = await resolveVisualReferencePresentationInput(reference, reader(value));
    expect(result.status).toBe(status);
    expect(result.input).toBeNull();
    expect(result.blocker_reasons).toEqual([reason]);
  });

  it('blocks missing and inaccessible exact Drive files without fallback', async () => {
    const missing = reader(null);
    const missingResult = await resolveVisualReferencePresentationInput(reference, missing);
    expect(missingResult.status).toBe('blocked');
    expect(missingResult.blocker_reasons).toEqual([VISUAL_REFERENCE_RESOLUTION_REASONS.fileMissing]);
    expect(missing.readExactImage).toHaveBeenCalledTimes(1);

    const inaccessible: ExactDriveImageReader = {
      readExactImage: vi.fn().mockRejectedValue(new Error('permission denied')),
    };
    const inaccessibleResult = await resolveVisualReferencePresentationInput(reference, inaccessible);
    expect(inaccessibleResult.status).toBe('blocked');
    expect(inaccessibleResult.blocker_reasons).toEqual([VISUAL_REFERENCE_RESOLUTION_REASONS.fileInaccessible]);
  });

  it('blocks before retrieval when the approved manifest has no exact external file ID', async () => {
    const exactReader = reader();
    const result = await resolveVisualReferencePresentationInput({
      ...reference,
      manifest_reference: { ...reference.manifest_reference, external_file_id: ' ' },
    }, exactReader);

    expect(result.status).toBe('blocked');
    expect(result.blocker_reasons).toEqual([VISUAL_REFERENCE_RESOLUTION_REASONS.externalFileIdMissing]);
    expect(exactReader.readExactImage).not.toHaveBeenCalled();
  });

  it('never accepts filename or folder resemblance as an identity substitute', async () => {
    const exactReader = reader({ ...observed, file_id: 'Digital Media/editor-add-content.png' });
    const result = await resolveVisualReferencePresentationInput(reference, exactReader);

    expect(result.status).toBe('blocked');
    expect(result.blocker_reasons).toEqual([VISUAL_REFERENCE_RESOLUTION_REASONS.externalFileIdMismatch]);
    expect(exactReader.readExactImage).toHaveBeenCalledWith('drive-file-exact-123');
  });
});
