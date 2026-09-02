import type { CaptureStatus } from './captureEvidence';
import type { ApprovedVisualReference } from './visualReference';

export const VISUAL_REFERENCE_RESOLUTION_REASONS = {
  externalFileIdMissing: 'visual-reference-external-file-id-missing',
  externalFileIdMismatch: 'visual-reference-external-file-id-mismatch',
  stableReferenceMismatch: 'visual-reference-stable-reference-mismatch',
  contentFingerprintMismatch: 'visual-reference-content-fingerprint-mismatch',
  fileMissing: 'visual-reference-file-missing',
  fileInaccessible: 'visual-reference-file-inaccessible',
  wrongMimeType: 'visual-reference-wrong-mime-type',
  stale: 'visual-reference-resolution-stale',
} as const;

export type VisualReferenceResolutionReason =
  (typeof VISUAL_REFERENCE_RESOLUTION_REASONS)[keyof typeof VISUAL_REFERENCE_RESOLUTION_REASONS];

export type DriveImageIdentity = Readonly<{
  file_id: string;
  mime_type: string;
  stable_ref: string;
  content_fingerprint: string;
  current: boolean;
}>;

export type ExactDriveImageReader = Readonly<{
  readExactImage(fileId: string): Promise<DriveImageIdentity | null>;
}>;

export type VisualReferencePresentationInput = Readonly<{
  reference_id: string;
  application: string;
  application_variant: string | null;
  context_state: string;
  manifest_id: string;
  external_file_id: string;
  asset_id: string;
  stable_ref: string;
  content_fingerprint: string;
  mime_type: string;
  source_reference: string;
  sanitized_derivative_reference: string;
  provenance: readonly string[];
  visible_ui_claims: readonly string[];
}>;

export type VisualReferenceResolutionResult = Readonly<{
  status: CaptureStatus;
  input: VisualReferencePresentationInput | null;
  blocker_reasons: readonly VisualReferenceResolutionReason[];
}>;

function blocked(reason: VisualReferenceResolutionReason, status: CaptureStatus = 'blocked'): VisualReferenceResolutionResult {
  return { status, input: null, blocker_reasons: [reason] };
}

/**
 * Resolve an already-approved visual reference to one exact Drive-backed image.
 * Eligibility is upstream authority: this function never searches, substitutes,
 * mutates, or manufactures approval. The injected reader receives only the exact
 * external file ID carried by the approved manifest reference.
 */
export async function resolveVisualReferencePresentationInput(
  reference: ApprovedVisualReference,
  reader: ExactDriveImageReader,
): Promise<VisualReferenceResolutionResult> {
  const expectedFileId = reference.manifest_reference.external_file_id.trim();
  if (!expectedFileId) return blocked(VISUAL_REFERENCE_RESOLUTION_REASONS.externalFileIdMissing);

  let observed: DriveImageIdentity | null;
  try {
    observed = await reader.readExactImage(expectedFileId);
  } catch {
    return blocked(VISUAL_REFERENCE_RESOLUTION_REASONS.fileInaccessible);
  }
  if (!observed) return blocked(VISUAL_REFERENCE_RESOLUTION_REASONS.fileMissing);
  if (observed.file_id !== expectedFileId) return blocked(VISUAL_REFERENCE_RESOLUTION_REASONS.externalFileIdMismatch);
  if (observed.stable_ref !== reference.asset_reference.stable_ref) {
    return blocked(VISUAL_REFERENCE_RESOLUTION_REASONS.stableReferenceMismatch);
  }
  if (observed.content_fingerprint !== reference.asset_reference.content_fingerprint) {
    return blocked(VISUAL_REFERENCE_RESOLUTION_REASONS.contentFingerprintMismatch, 'stale');
  }
  if (!observed.current) return blocked(VISUAL_REFERENCE_RESOLUTION_REASONS.stale, 'stale');
  if (!observed.mime_type.startsWith('image/')) return blocked(VISUAL_REFERENCE_RESOLUTION_REASONS.wrongMimeType);

  return {
    status: 'valid',
    blocker_reasons: [],
    input: {
      reference_id: reference.reference_id,
      application: reference.application,
      application_variant: reference.application_variant,
      context_state: reference.context_state,
      manifest_id: reference.manifest_reference.manifest_id,
      external_file_id: expectedFileId,
      asset_id: reference.asset_reference.asset_id,
      stable_ref: reference.asset_reference.stable_ref,
      content_fingerprint: reference.asset_reference.content_fingerprint,
      mime_type: observed.mime_type,
      source_reference: reference.source_reference,
      sanitized_derivative_reference: reference.sanitized_derivative_reference,
      provenance: [...reference.provenance],
      visible_ui_claims: [...reference.visible_ui_claims],
    },
  };
}
