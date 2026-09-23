import { describe, expect, it } from 'vitest';
import {
  admitVisualReference,
  selectVisualReference,
  type VisualReferenceCandidate,
  type VisualReferenceLibrary,
} from './visualReference';

const sourceDriveId = '1RCIn3aDHfafrtyCQjfqFqJsu5gVuVP0Y';
const derivativeDriveId = '1ovc70FMLRyNS-ibqmlErHQ0HPK6Elqeg';
const derivativeSha256 = 'ae911a2c036a9c288b194f6c2e6b7b4591ddf148c113f28d40cfeb3c9b192497';
const derivativeAssetId = 'visual-asset-6378271ff798853d5b9f99da';
const derivativeStableRef =
  'visual-ref-6378271ff798853d5b9f99da71ff6f31752e889d58fbad6818584b2877300115';

const candidate: VisualReferenceCandidate = {
  reference_id: 'adobe-editor-add-content-1377',
  application: 'Adobe Express',
  application_variant: 'Education',
  context_state: 'editor/add-content',
  source: {
    source_reference: `drive:${sourceDriveId}`,
    source_kind: 'teacher-supplied-screenshot',
    captured_at: '2026-06-05T22:23:28Z',
    provenance: [
      'github-issue-1377-comment-5401561490',
      'github-issue-1377-comment-5401660536',
      'source-sha256:d0a72869d60024921876261a545c00a2e943ac767a7ef71978bcf2048835802e',
    ],
  },
  sanitized_derivative_reference: `drive:${derivativeDriveId}`,
  sanitization: {
    browser_chrome_removed: true,
    private_context_removed: true,
  },
  visible_ui_claims: [
    'Adobe Express for Education',
    'Add content',
    'Media',
    'Elements',
    'Charts and grids',
    'Generative AI',
  ],
  manifest_reference: {
    manifest_id: 'standalone-manifest-1377-add-content',
    record_revision: 1,
    fingerprint: '4310b3c44c71f129cfec3d144c6abc27954cd29c378390a3f6bc70819f685588',
    verified_at: '2026-08-28T21:15:00Z',
    external_file_id: derivativeDriveId,
  },
  asset_reference: {
    asset_id: derivativeAssetId,
    stable_ref: derivativeStableRef,
    content_fingerprint: derivativeSha256,
  },
  artifact_manifest: {
    contract_version: 'curriculum-artifact-manifest-v2',
    external_identity: { access_state: 'verified' },
    statuses: { classroom_readiness: 'ready' },
    asset: {
      privacy_resolved: true,
      residual_privacy_risk: false,
      rights_classification: 'cleared-internal',
      direct_use_status: 'student-ready',
      replacement_required: false,
      transformations: ['replace'],
    },
  },
  compatibility: {
    contract_version: 'curriculum-visual-asset-compatibility-v2',
    classification: 'eligible',
    cohesion_profile: {
      medium: 'screen-capture',
      representation_class: 'interface-capture',
    },
    freshness: { stale: false },
  },
};

describe('PPUX-VRL4 real Adobe Express Add Content pilot', () => {
  it('admits the exact validated #1377 derivative as one ApprovedVisualReference', () => {
    const result = admitVisualReference(candidate);

    expect(result.status).toBe('valid');
    expect(result.blocker_reasons).toEqual([]);
    expect(result.reference).not.toBeNull();
    expect(result.reference?.reference_id).toBe('adobe-editor-add-content-1377');
    expect(result.reference?.application).toBe('Adobe Express');
    expect(result.reference?.application_variant).toBe('Education');
    expect(result.reference?.context_state).toBe('editor/add-content');
    expect(result.reference?.source_reference).toBe(`drive:${sourceDriveId}`);
    expect(result.reference?.sanitized_derivative_reference).toBe(`drive:${derivativeDriveId}`);
    expect(result.reference?.asset_reference).toEqual({
      asset_id: derivativeAssetId,
      stable_ref: derivativeStableRef,
      content_fingerprint: derivativeSha256,
    });
  });

  it('selects that one state-local reference without cross-reference claim unioning', () => {
    const admitted = admitVisualReference(candidate);
    expect(admitted.status).toBe('valid');
    expect(admitted.reference).not.toBeNull();

    const library: VisualReferenceLibrary = { references: [admitted.reference!] };
    expect(library.references).toHaveLength(1);

    const selection = selectVisualReference(library, {
      application: 'Adobe Express',
      application_variant: 'Education',
      context_state: 'editor/add-content',
      required_ui_claims: ['Add content', 'Media', 'Elements', 'Generative AI'],
    });

    expect(selection.status).toBe('valid');
    expect(selection.blocker_reasons).toEqual([]);
    expect(selection.reference?.reference_id).toBe('adobe-editor-add-content-1377');
    expect(selection.reference?.visible_ui_claims).toEqual([
      'Add content',
      'Adobe Express for Education',
      'Charts and grids',
      'Elements',
      'Generative AI',
      'Media',
    ]);
  });
});
