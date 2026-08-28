import { describe, expect, it } from 'vitest';
import type {
  ArtifactManifestAssetEvidence,
  AssetReference,
  ManifestReference,
  VisualAssetCompatibilityEvidence,
} from './captureEvidence';
import {
  VISUAL_REFERENCE_BLOCKER_REASONS,
  admitVisualReference,
  buildVisualReferenceDirective,
  selectVisualReference,
  type ApprovedVisualReference,
  type VisualReferenceCandidate,
  type VisualReferenceLibrary,
} from './visualReference';

const manifestReference: ManifestReference = {
  manifest_id: 'manifest-adobe-current-ui',
  record_revision: 1,
  fingerprint: 'manifest-fingerprint',
  verified_at: '2026-08-24T15:00:00Z',
  external_file_id: 'sanitized-ui-fixture',
};

const artifactManifest: ArtifactManifestAssetEvidence = {
  contract_version: 'curriculum-artifact-manifest-v1',
  external_identity: { access_state: 'verified' },
  statuses: { classroom_readiness: 'ready' },
  asset: {
    privacy_resolved: true,
    residual_privacy_risk: false,
    rights_classification: 'cleared-internal',
    direct_use_status: 'student-ready',
    replacement_required: false,
    transformations: ['crop', 'remove-browser-chrome', 'remove-private-context'],
  },
};

const compatibility: VisualAssetCompatibilityEvidence = {
  contract_version: 'curriculum-visual-asset-compatibility-v2',
  classification: 'eligible',
  cohesion_profile: { medium: 'screen-capture', representation_class: 'interface-capture' },
  freshness: { stale: false },
};

function candidate(
  contextState: string,
  visibleClaims: readonly string[],
  overrides: Partial<VisualReferenceCandidate> = {},
): VisualReferenceCandidate {
  const id = contextState.replaceAll('/', '-');
  const assetReference: AssetReference = {
    asset_id: `asset-${id}`,
    stable_ref: `visual-reference://${id}`,
    content_fingerprint: `fingerprint-${id}`,
  };
  return {
    reference_id: `adobe-${id}`,
    application: 'Adobe Express',
    application_variant: 'Education',
    context_state: contextState,
    source: {
      source_reference: `teacher-upload://${id}`,
      source_kind: 'teacher-supplied-screenshot',
      captured_at: '2026-08-24T14:57:20Z',
      provenance: ['PPUX live test 2026-08-24', `source-state:${contextState}`],
    },
    sanitized_derivative_reference: `sanitized://${id}`,
    sanitization: { browser_chrome_removed: true, private_context_removed: true },
    visible_ui_claims: visibleClaims,
    manifest_reference: { ...manifestReference, external_file_id: `sanitized-${id}` },
    asset_reference: assetReference,
    artifact_manifest: artifactManifest,
    compatibility,
    ...overrides,
  };
}

function approved(contextState: string, visibleClaims: readonly string[]): ApprovedVisualReference {
  const result = admitVisualReference(candidate(contextState, visibleClaims));
  if (result.status !== 'valid' || !result.reference) throw new Error(`fixture admission failed: ${contextState}`);
  return result.reference;
}

const library: VisualReferenceLibrary = {
  references: [
    approved('navigation/your-stuff/files', ['Adobe Express', 'Your stuff', 'Files', 'Digital Media', 'Create']),
    approved('navigation/create-menu', ['Adobe Express', 'Create', 'Create file', 'Create folder', 'Upload']),
    approved('creation/get-started', ['Adobe Express', 'Square', '1:1', 'Landscape', '16:9', 'Portrait', '9:16']),
    approved('editor/add-content', ['Adobe Express', 'Add content', 'Media', 'Elements', 'Charts and grids', 'Generative AI']),
    approved('editor/media', ['Adobe Express', 'Media', 'Upload from device', 'Generate image']),
    approved('editor/text/edit', ['Adobe Express', 'Text', 'Edit', 'Add your text', 'Title', 'Heading', 'Body']),
    approved('editor/text/effects', ['Adobe Express', 'Text', 'Effects', 'Generate text effects', 'Shadow']),
    approved('editor/text/animation', ['Adobe Express', 'Text', 'Animation', 'Animate all', 'Bounce', 'Wobble']),
    approved('editor/image/edit', ['Adobe Express', 'Image', 'Edit', 'Remove background', 'Erase', 'Remove object']),
    approved('editor/image/effects', ['Adobe Express', 'Image', 'Effects', 'Photoshop Filters', 'Duotone']),
    approved('editor/image/animation', ['Adobe Express', 'Image', 'Animation', 'Bounce', 'Wobble']),
    approved('editor/elements/backgrounds', ['Adobe Express', 'Elements', 'Backgrounds', 'Search backgrounds']),
    approved('editor/elements/background-filters', ['Adobe Express', 'Filters', 'Generative AI', 'Orientation', 'Horizontal', 'Vertical', 'Square']),
    approved('editor/elements/shapes', ['Adobe Express', 'Elements', 'Shapes', 'Draw shape', 'Search shapes']),
    approved('editor/shape/edit', ['Adobe Express', 'Rectangle', 'Edit', 'Border style', 'Border thickness', 'Corner roundness']),
    approved('editor/shape/fill-color', ['Adobe Express', 'Shape color', 'Swatches', 'Custom', 'Gradients']),
    approved('editor/shape/border-color', ['Adobe Express', 'Border color', 'Swatches', 'Custom', 'Gradients']),
  ],
};

describe('PPUX-VRL1 current application visual-reference library', () => {
  it('admits only a distinct sanitized derivative with preserved provenance', () => {
    const admitted = admitVisualReference(candidate('navigation/home', ['Adobe Express']));
    expect(admitted.status).toBe('valid');
    expect(admitted.reference?.source_reference).toBe('teacher-upload://navigation-home');
    expect(admitted.reference?.sanitized_derivative_reference).toBe('sanitized://navigation-home');
    expect(admitted.reference?.provenance).toContain('PPUX live test 2026-08-24');

    const rawOnly = admitVisualReference(candidate('navigation/home', ['Adobe Express'], {
      sanitized_derivative_reference: null,
      sanitization: { browser_chrome_removed: false, private_context_removed: false },
    }));
    expect(rawOnly.status).toBe('blocked');
    expect(rawOnly.blocker_reasons).toContain(VISUAL_REFERENCE_BLOCKER_REASONS.sanitizedDerivativeMissing);
  });

  it('admits the governed standalone manifest v2 path without weakening eligibility gates', () => {
    const result = admitVisualReference(candidate('editor/add-content', ['Adobe Express', 'Add content'], {
      artifact_manifest: { ...artifactManifest, contract_version: 'curriculum-artifact-manifest-v2' },
    }));
    expect(result.status).toBe('valid');
    expect(result.reference?.context_state).toBe('editor/add-content');
  });

  it('keeps crop-only privacy unresolved out of Ready', () => {
    const result = admitVisualReference(candidate('navigation/home', ['Adobe Express'], {
      artifact_manifest: {
        ...artifactManifest,
        asset: {
          ...artifactManifest.asset,
          privacy_resolved: false,
          transformations: ['crop'],
        },
      },
    }));
    expect(result.status).toBe('manual-review-required');
    expect(result.blocker_reasons).toContain(VISUAL_REFERENCE_BLOCKER_REASONS.privacyUnresolved);
  });

  it('keeps stale current-UI references out of Ready', () => {
    const result = admitVisualReference(candidate('navigation/home', ['Adobe Express'], {
      compatibility: { ...compatibility, freshness: { stale: true } },
    }));
    expect(result.status).toBe('stale');
    expect(result.blocker_reasons).toContain(VISUAL_REFERENCE_BLOCKER_REASONS.stale);
  });

  it('retrieves Your Stuff / Files without widening into another Adobe context', () => {
    const result = selectVisualReference(library, {
      application: 'Adobe Express',
      application_variant: 'Education',
      context_state: 'navigation/your-stuff/files',
      required_ui_claims: ['Your stuff', 'Digital Media'],
    });
    expect(result.status).toBe('valid');
    expect(result.reference?.context_state).toBe('navigation/your-stuff/files');
    expect(result.reference?.visible_ui_claims).not.toContain('Create file');
  });

  it('detects the Tutorial 0 Create new -> Create / Create file drift instead of silently substituting', () => {
    const result = selectVisualReference(library, {
      application: 'Adobe Express',
      application_variant: 'Education',
      context_state: 'navigation/create-menu',
      required_ui_claims: ['Create file'],
      recorded_ui_claims: ['Create new'],
    });
    expect(result.status).toBe('manual-review-required');
    expect(result.blocker_reasons).toEqual([VISUAL_REFERENCE_BLOCKER_REASONS.currentRecordedUiConflict]);
  });

  it('selects the current Landscape 16:9 Get started state when claims are co-visible', () => {
    const result = selectVisualReference(library, {
      application: 'Adobe Express',
      application_variant: 'Education',
      context_state: 'creation/get-started',
      required_ui_claims: ['Landscape', '16:9'],
      recorded_ui_claims: ['Landscape', '16:9'],
    });
    expect(result.status).toBe('valid');
    expect(result.reference?.context_state).toBe('creation/get-started');
  });

  it('keeps Add Content / Media separate from Elements and Text states', () => {
    const media = selectVisualReference(library, {
      application: 'Adobe Express',
      application_variant: 'Education',
      context_state: 'editor/media',
      required_ui_claims: ['Upload from device'],
    });
    expect(media.status).toBe('valid');
    expect(media.reference?.visible_ui_claims).not.toContain('Search shapes');
    expect(media.reference?.visible_ui_claims).not.toContain('Add your text');
  });

  it.each([
    ['editor/text/edit', 'Edit'],
    ['editor/text/effects', 'Effects'],
    ['editor/text/animation', 'Animation'],
    ['editor/image/edit', 'Remove background'],
    ['editor/image/effects', 'Photoshop Filters'],
    ['editor/image/animation', 'Animation'],
  ])('keeps object-specific editing state %s distinct', (context_state, claim) => {
    const result = selectVisualReference(library, {
      application: 'Adobe Express',
      application_variant: 'Education',
      context_state,
      required_ui_claims: [claim],
    });
    expect(result.status).toBe('valid');
    expect(result.reference?.context_state).toBe(context_state);
  });

  it('retrieves Backgrounds and background filters as different states', () => {
    const backgrounds = selectVisualReference(library, {
      application: 'Adobe Express',
      application_variant: 'Education',
      context_state: 'editor/elements/backgrounds',
      required_ui_claims: ['Search backgrounds'],
    });
    const filters = selectVisualReference(library, {
      application: 'Adobe Express',
      application_variant: 'Education',
      context_state: 'editor/elements/background-filters',
      required_ui_claims: ['Orientation', 'Square'],
    });
    expect(backgrounds.status).toBe('valid');
    expect(filters.status).toBe('valid');
    expect(backgrounds.reference?.reference_id).not.toBe(filters.reference?.reference_id);
  });

  it('keeps Shapes, Rectangle edit, fill color, and border color as separate references', () => {
    for (const [context_state, claim] of [
      ['editor/elements/shapes', 'Draw shape'],
      ['editor/shape/edit', 'Corner roundness'],
      ['editor/shape/fill-color', 'Shape color'],
      ['editor/shape/border-color', 'Border color'],
    ] as const) {
      const result = selectVisualReference(library, {
        application: 'Adobe Express',
        application_variant: 'Education',
        context_state,
        required_ui_claims: [claim],
      });
      expect(result.status).toBe('valid');
      expect(result.reference?.context_state).toBe(context_state);
    }
  });

  it('never unions claims from different screenshots to fabricate co-visibility', () => {
    const splitLibrary: VisualReferenceLibrary = {
      references: [
        approved('editor/shell', ['Adobe Express', 'Share']),
        approved('editor/shell', ['Adobe Express', 'Assign']),
      ],
    };
    const result = selectVisualReference(splitLibrary, {
      application: 'Adobe Express',
      application_variant: 'Education',
      context_state: 'editor/shell',
      required_ui_claims: ['Share', 'Assign'],
    });
    expect(result.status).toBe('blocked');
    expect(result.blocker_reasons).toEqual([VISUAL_REFERENCE_BLOCKER_REASONS.claimsNotCoVisible]);
  });

  it('builds a presentation directive that preserves the exact state and prohibits reconstruction/mixing', () => {
    const result = selectVisualReference(library, {
      application: 'Adobe Express',
      application_variant: 'Education',
      context_state: 'editor/shape/border-color',
      required_ui_claims: ['Border color'],
    });
    expect(result.status).toBe('valid');
    const directive = buildVisualReferenceDirective(result.reference!);
    expect(directive).toContain('visual-reference://editor-shape-border-color');
    expect(directive).toContain('editor/shape/border-color');
    expect(directive).toContain('Do not redraw, reconstruct, invent, or merge');
  });
});
