import type { ApprovedVisualReference, VisualReferenceLibrary } from '../visualReference';

function reference(
  referenceId: string,
  contextState: string,
  visibleUiClaims: readonly string[],
): ApprovedVisualReference {
  return {
    reference_id: referenceId,
    application: 'Adobe Express',
    application_variant: 'Education',
    context_state: contextState,
    captured_at: '2026-08-24T14:57:20Z',
    verified_at: '2026-08-24T15:00:00Z',
    sanitized_derivative_reference: `sanitized://${referenceId}`,
    source_reference: `teacher-upload://${referenceId}`,
    provenance: ['PPUX live test 2026-08-24', `source-state:${contextState}`],
    visible_ui_claims: visibleUiClaims,
    manifest_reference: {
      manifest_id: `manifest-${referenceId}`,
      record_revision: 1,
      fingerprint: `manifest-fingerprint-${referenceId}`,
      verified_at: '2026-08-24T15:00:00Z',
      external_file_id: `sanitized-${referenceId}`,
    },
    asset_reference: {
      asset_id: `asset-${referenceId}`,
      stable_ref: `visual-reference://${referenceId}`,
      content_fingerprint: `fingerprint-${referenceId}`,
    },
  };
}

/** Privacy-safe metadata fixture representing the reviewed current Adobe Express states. */
export const tutorial0CurrentVisualReferences: VisualReferenceLibrary = {
  references: [
    reference(
      'tutorial0-your-stuff-files',
      'navigation/your-stuff/files',
      ['Adobe Express', 'Your stuff', 'Files', 'Digital Media', 'Create'],
    ),
    reference(
      'tutorial0-create-menu',
      'navigation/create-menu',
      ['Adobe Express', 'Create', 'Create file', 'Create folder', 'Upload'],
    ),
    reference(
      'tutorial0-get-started',
      'creation/get-started',
      ['Adobe Express', 'Square', '1:1', 'Landscape', '16:9', 'Portrait', '9:16'],
    ),
  ],
};
