import { describe, expect, it } from 'vitest';
import {
  AUTHORITATIVE_REPORT_FIELDS,
  DIAGNOSTIC_REPORT_FIELDS,
  EXACT_COMPOSITE_OPERATIONS,
  EXECUTOR_BLOCKER_REASONS,
  EXECUTOR_PROVENANCE_REPORT_VERSION,
  FORBIDDEN_EXECUTOR_BEHAVIOURS,
  admitExecutionRequest,
  isAuthoritativeReportField,
  type ExactCompositeArtifact,
  type ExactCompositeExecutionRequest,
  type ExactCompositeExecutor,
  type ExecutorProvenanceReport,
} from './executorContract';
import {
  DEFAULT_EXACT_COMPOSITE_RENDER_SPEC,
  RECT_CONVENTION,
  RECT_SPACES,
  RENDER_MODES,
  RESAMPLERS,
  TUTORIAL_FRAME_PLAN_VERSION,
  type TutorialFramePlan,
} from './framePlan';

const source: ExactCompositeArtifact = {
  sha256: 'a'.repeat(64),
  width_px: 1280,
  height_px: 720,
  bytes: new Uint8Array(0),
};

function planWith(overrides: Partial<TutorialFramePlan> = {}): TutorialFramePlan {
  return {
    plan_version: TUTORIAL_FRAME_PLAN_VERSION,
    rect_convention: RECT_CONVENTION,
    base_reference: {
      reference_id: 'adobe-editor-add-content',
      stable_ref: 'asset://sanitized/editor-add-content',
      content_fingerprint: 'sha256:approved-image',
    },
    resolved_target_region_id: 'add-content-button',
    source_rect: { space: RECT_SPACES.sourcePixel, rect: [0, 0, 1280, 720] },
    output_aspect: { width: 16, height: 9 },
    output_width_px: 1280,
    output_height_px: 720,
    render_mode: RENDER_MODES.cropOnly,
    scale_x: 1,
    scale_y: 1,
    render_spec: DEFAULT_EXACT_COMPOSITE_RENDER_SPEC,
    asset_fills: [],
    overlays: [],
    anchored_rects: [{ region_id: 'add-content-button', rect: { space: RECT_SPACES.outputPixel, rect: [400, 300, 240, 80] } }],
    must_show_region_ids: ['add-content-button'],
    annotation_intent: { target_region_id: 'add-content-button', label: 'Add content', preferred_side: 'right' },
    execution_authorized: false,
    ...overrides,
  };
}

const requestWith = (plan: TutorialFramePlan, assets: ExactCompositeExecutionRequest['assets'] = []): ExactCompositeExecutionRequest =>
  ({ plan, source, assets });

const report: ExecutorProvenanceReport = {
  report_version: EXECUTOR_PROVENANCE_REPORT_VERSION,
  rect_convention: RECT_CONVENTION,
  source_sha256: 'a'.repeat(64),
  source_width_px: 1280,
  source_height_px: 720,
  plan_sha256: 'b'.repeat(64),
  output_sha256: 'c'.repeat(64),
  output_width_px: 1280,
  output_height_px: 720,
  source_rect: { space: RECT_SPACES.sourcePixel, rect: [0, 0, 1280, 720] },
  scale_x: 1,
  scale_y: 1,
  resampler: RESAMPLERS.none,
  compositing_colour_space: 'srgb',
  render_mode: RENDER_MODES.cropOnly,
  generation_used: false,
  executed_dim_rgba: [0, 0, 0, 0.55],
  executed_spotlight: null,
  overlay_masks: [],
  overlay_bleed_px: DEFAULT_EXACT_COMPOSITE_RENDER_SPEC.overlay_bleed_px,
  asset_placements: [],
  diagnostics: {
    executor_id: null,
    executor_version: null,
    narrative: null,
    elapsed_ms: null,
    step_trace: null,
    recovered_spotlight_estimate: null,
  },
};

describe('ExactCompositeExecutor contract', () => {
  it('is satisfiable with only plan, source, and assets', async () => {
    const executor: ExactCompositeExecutor = {
      execute: async (request) => ({
        image: { sha256: 'c'.repeat(64), width_px: request.plan.output_width_px, height_px: request.plan.output_height_px, bytes: new Uint8Array(0) },
        report,
      }),
    };

    const output = await executor.execute(requestWith(planWith()));

    expect(output.image.width_px).toBe(1280);
    expect(output.report.report_version).toBe(EXECUTOR_PROVENANCE_REPORT_VERSION);
  });

  it('enumerates exactly the allowed exact-composite operations', () => {
    expect([...EXACT_COMPOSITE_OPERATIONS]).toEqual([
      'crop', 'proportional-scale', 'dim', 'spotlight', 'badge', 'arrow', 'label',
      'magnified-source-pixel-inset', 'approved-exact-asset-placement',
    ]);
    expect(Object.isFrozen(EXACT_COMPOSITE_OPERATIONS)).toBe(true);
  });

  it('forbids every runtime discovery and judgment behaviour', () => {
    expect([...FORBIDDEN_EXECUTOR_BEHAVIOURS]).toEqual([
      'locate-targets', 'detect-handles', 'threshold-pixels', 'scan-brightness',
      'infer-canvas-bounds', 'estimate-geometry', 'choose-framing',
      'move-annotations-for-aesthetics', 'recover-missing-plan-values',
      'reconstruct-source-ui-or-artwork',
    ]);
    expect(Object.isFrozen(FORBIDDEN_EXECUTOR_BEHAVIOURS)).toBe(true);
  });

  it('names no provider, service, model, or credential', () => {
    const serialized = JSON.stringify({ plan: planWith(), report }).toLowerCase();
    for (const token of ['openai', 'anthropic', 'gemini', 'firefly', 'midjourney', 'stability', 'provider', 'model_id', 'api_key', 'endpoint', 'credential']) {
      expect(serialized).not.toContain(token);
    }
  });
});

describe('ExecutorProvenanceReport authoritative/diagnostic separation', () => {
  it('separates authoritative fields from diagnostics structurally', () => {
    const topLevel = Object.keys(report).filter((field) => field !== 'diagnostics');

    expect(topLevel).toEqual([...AUTHORITATIVE_REPORT_FIELDS]);
    expect(Object.keys(report.diagnostics)).toEqual([...DIAGNOSTIC_REPORT_FIELDS]);
  });

  it('treats no diagnostic field as authoritative', () => {
    for (const field of DIAGNOSTIC_REPORT_FIELDS) {
      expect(isAuthoritativeReportField(field)).toBe(false);
    }
    for (const field of AUTHORITATIVE_REPORT_FIELDS) {
      expect(isAuthoritativeReportField(field)).toBe(true);
    }
  });

  it('keeps a recovered spotlight estimate out of the executed record', () => {
    expect(isAuthoritativeReportField('recovered_spotlight_estimate')).toBe(false);
    expect(isAuthoritativeReportField('executed_spotlight')).toBe(true);
  });

  it('carries generation_used as an attestation alongside verifiable identity', () => {
    expect(report.generation_used).toBe(false);
    expect(report.source_sha256).toHaveLength(64);
    expect(report.plan_sha256).toHaveLength(64);
    expect(report.output_sha256).toHaveLength(64);
    expect(report.rect_convention).toBe('xywh');
  });
});

describe('admitExecutionRequest fail-closed behaviour', () => {
  it('admits a complete request', () => {
    const result = admitExecutionRequest(requestWith(planWith()));

    expect(result.status).toBe('valid');
    expect(result.blocker_reasons).toEqual([]);
    expect(result.request).not.toBeNull();
  });

  it('blocks an unsupported plan version', () => {
    const plan = { ...planWith(), plan_version: 'exact-composite-plan-v0' } as unknown as TutorialFramePlan;
    const result = admitExecutionRequest(requestWith(plan));

    expect(result.request).toBeNull();
    expect(result.blocker_reasons).toContain(EXECUTOR_BLOCKER_REASONS.planVersionUnsupported);
  });

  it('blocks an unsupported rect convention', () => {
    const plan = { ...planWith(), rect_convention: 'ltrb' } as unknown as TutorialFramePlan;
    const result = admitExecutionRequest(requestWith(plan));

    expect(result.blocker_reasons).toContain(EXECUTOR_BLOCKER_REASONS.rectConventionUnsupported);
  });

  it('blocks an invalid source artifact', () => {
    const result = admitExecutionRequest({ plan: planWith(), source: { ...source, sha256: '  ' }, assets: [] });

    expect(result.blocker_reasons).toContain(EXECUTOR_BLOCKER_REASONS.sourceArtifactInvalid);
  });

  it('blocks a source rect outside the source artifact', () => {
    const plan = planWith({ source_rect: { space: RECT_SPACES.sourcePixel, rect: [100, 0, 1280, 720] } });
    const result = admitExecutionRequest(requestWith(plan));

    expect(result.blocker_reasons).toContain(EXECUTOR_BLOCKER_REASONS.sourceRectOutOfBounds);
  });

  it('blocks output dimensions inconsistent with the declared aspect', () => {
    const plan = planWith({ output_aspect: { width: 4, height: 3 } });
    const result = admitExecutionRequest(requestWith(plan));

    expect(result.blocker_reasons).toContain(EXECUTOR_BLOCKER_REASONS.outputGeometryInconsistent);
  });

  it('blocks a scale that does not match the geometry', () => {
    const result = admitExecutionRequest(requestWith(planWith({ scale_x: 2, scale_y: 2 })));

    expect(result.blocker_reasons).toContain(EXECUTOR_BLOCKER_REASONS.scaleInconsistent);
  });

  it('blocks a non-proportional scale', () => {
    const result = admitExecutionRequest(requestWith(planWith({ scale_x: 1, scale_y: 1.5 })));

    expect(result.blocker_reasons).toContain(EXECUTOR_BLOCKER_REASONS.scaleInconsistent);
  });

  it('blocks an overlay outside the output frame', () => {
    const plan = planWith({
      overlays: [{
        overlay_id: 'badge-1',
        kind: 'badge',
        bounds: { space: RECT_SPACES.outputPixel, rect: [1260, 700, 44, 44] },
        ordinal: 1,
        centre_x_px: 1282,
        centre_y_px: 722,
      }],
    });
    const result = admitExecutionRequest(requestWith(plan));

    expect(result.blocker_reasons).toContain(EXECUTOR_BLOCKER_REASONS.overlayOutOfBounds);
  });

  it('blocks an asset fill with no supplied asset', () => {
    const plan = planWith({
      asset_fills: [{
        fill_id: 'fill-1',
        asset_id: 'asset-callout',
        asset_fingerprint: 'sha256:callout',
        destination: { space: RECT_SPACES.outputPixel, rect: [0, 0, 40, 40] },
      }],
    });
    const result = admitExecutionRequest(requestWith(plan));

    expect(result.blocker_reasons).toContain(EXECUTOR_BLOCKER_REASONS.assetUnavailable);
  });

  it('blocks an asset whose fingerprint does not match the plan', () => {
    const plan = planWith({
      asset_fills: [{
        fill_id: 'fill-1',
        asset_id: 'asset-callout',
        asset_fingerprint: 'sha256:callout',
        destination: { space: RECT_SPACES.outputPixel, rect: [0, 0, 40, 40] },
      }],
    });
    const result = admitExecutionRequest(requestWith(plan, [{
      asset_id: 'asset-callout',
      asset_fingerprint: 'sha256:recaptured-callout',
      artifact: { sha256: 'd'.repeat(64), width_px: 40, height_px: 40, bytes: new Uint8Array(0) },
    }]));

    expect(result.blocker_reasons).toContain(EXECUTOR_BLOCKER_REASONS.assetFingerprintMismatch);
  });
});
