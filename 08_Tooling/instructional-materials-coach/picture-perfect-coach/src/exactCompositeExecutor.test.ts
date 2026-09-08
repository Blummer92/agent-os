import { describe, expect, it } from 'vitest';
import {
  DETERMINISTIC_EXACT_COMPOSITE_EXECUTOR_ID,
  DETERMINISTIC_EXECUTOR_BLOCKER_REASONS,
  DeterministicExactCompositeExecutionError,
  deterministicExactCompositeExecutor,
  toExactCompositeArtifact,
} from './exactCompositeExecutor';
import { createImage, getPixel, imageSha256, planSha256, setPixel, utf8Bytes } from './exactCompositePrimitives';
import {
  DEFAULT_EXACT_COMPOSITE_RENDER_SPEC,
  RECT_CONVENTION,
  RECT_SPACES,
  RENDER_MODES,
  TUTORIAL_FRAME_PLAN_VERSION,
  type TutorialFramePlan,
} from './framePlan';
import { validatePixelFidelity, validateReportIntegrity } from './provenanceValidator';
import { createFixtureSource } from './fixtures/exactCompositeFixture';

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
    source_rect: { space: RECT_SPACES.sourcePixel, rect: [0, 0, 32, 18] },
    output_aspect: { width: 16, height: 9 },
    output_width_px: 32,
    output_height_px: 18,
    render_mode: RENDER_MODES.cropOnly,
    scale_x: 1,
    scale_y: 1,
    render_spec: DEFAULT_EXACT_COMPOSITE_RENDER_SPEC,
    asset_fills: [],
    overlays: [{
      overlay_id: 'spotlight-1',
      kind: 'spotlight',
      bounds: { space: RECT_SPACES.outputPixel, rect: [6, 2, 16, 12] },
      region_id: 'add-content-button',
      boundary: { space: RECT_SPACES.outputPixel, rect: [8, 4, 12, 8] },
      padding_px: 2,
      falloff_px: 2,
      falloff_function: 'smoothstep',
    }],
    anchored_rects: [{ region_id: 'add-content-button', rect: { space: RECT_SPACES.outputPixel, rect: [8, 4, 12, 8] } }],
    must_show_region_ids: ['add-content-button'],
    annotation_intent: { target_region_id: 'add-content-button', label: 'Add content', preferred_side: 'right' },
    execution_authorized: false,
    ...overrides,
  };
}

const sourceImage = createFixtureSource(32, 18);
const sourceArtifact = toExactCompositeArtifact(sourceImage);

function artifactToImage(artifact: ReturnType<typeof toExactCompositeArtifact>) {
  const headerLength = utf8Bytes(`ppux-rgba8:${artifact.width_px}x${artifact.height_px}:`).length;
  return {
    width: artifact.width_px,
    height: artifact.height_px,
    data: new Uint8ClampedArray(artifact.bytes.slice(headerLength)),
  };
}

describe('deterministicExactCompositeExecutor', () => {
  it('implements the provider-neutral contract and passes both mechanical gates', async () => {
    const plan = planWith();
    const output = await deterministicExactCompositeExecutor.execute({ plan, source: sourceArtifact, assets: [] });
    const outputImage = artifactToImage(output.image);

    expect(output.report.diagnostics.executor_id).toBe(DETERMINISTIC_EXACT_COMPOSITE_EXECUTOR_ID);
    expect(output.report.generation_used).toBe(false);
    expect(output.report.source_sha256).toBe(imageSha256(sourceImage));
    expect(output.report.plan_sha256).toBe(planSha256(plan));
    expect(output.report.output_sha256).toBe(imageSha256(outputImage));

    const gateA = validatePixelFidelity({ plan, source: sourceImage, output: outputImage });
    const gateB = validateReportIntegrity({ plan, report: output.report, source: sourceImage, output: outputImage });
    expect(gateA.passed).toBe(true);
    expect(gateB.passed).toBe(true);
  });

  it('is byte-for-byte deterministic for identical source, plan, and assets', async () => {
    const request = { plan: planWith(), source: sourceArtifact, assets: [] } as const;
    const first = await deterministicExactCompositeExecutor.execute(request);
    const second = await deterministicExactCompositeExecutor.execute(request);

    expect(first.image.sha256).toBe(second.image.sha256);
    expect(Array.from(first.image.bytes)).toEqual(Array.from(second.image.bytes));
    expect(first.report).toEqual(second.report);
  });

  it('places only supplied approved exact assets and binds their provenance', async () => {
    const assetImage = createImage(2, 2, [7, 8, 9, 1]);
    const assetArtifact = toExactCompositeArtifact(assetImage);
    const plan = planWith({
      asset_fills: [{
        fill_id: 'fill-1',
        asset_id: 'callout',
        asset_fingerprint: 'sha256:callout',
        destination: { space: RECT_SPACES.outputPixel, rect: [10, 6, 2, 2] },
      }],
    });
    const output = await deterministicExactCompositeExecutor.execute({
      plan,
      source: sourceArtifact,
      assets: [{ asset_id: 'callout', asset_fingerprint: 'sha256:callout', artifact: assetArtifact }],
    });
    const outputImage = artifactToImage(output.image);

    expect(getPixel(outputImage, 10, 6)).toEqual([7, 8, 9, 1]);
    expect(output.report.asset_placements).toEqual([{
      fill_id: 'fill-1',
      asset_id: 'callout',
      asset_fingerprint: 'sha256:callout',
      destination: { space: 'output-pixel', rect: [10, 6, 2, 2] },
    }]);
  });

  it('adds no overlay pixels for a zero-overlay plan', async () => {
    const plan = planWith({ overlays: [], render_spec: { ...DEFAULT_EXACT_COMPOSITE_RENDER_SPEC, dim_rgba: [0, 0, 0, 0] } });
    const output = await deterministicExactCompositeExecutor.execute({ plan, source: sourceArtifact, assets: [] });
    const outputImage = artifactToImage(output.image);

    expect(output.report.overlay_masks).toEqual([]);
    expect(Array.from(outputImage.data)).toEqual(Array.from(sourceImage.data));
  });

  it('fails closed when source bytes do not match their declared digest', async () => {
    const bytes = new Uint8Array(sourceArtifact.bytes);
    bytes[bytes.length - 1] ^= 1;

    await expect(deterministicExactCompositeExecutor.execute({
      plan: planWith(),
      source: { ...sourceArtifact, bytes },
      assets: [],
    })).rejects.toMatchObject({
      name: 'DeterministicExactCompositeExecutionError',
      blocker_reasons: [DETERMINISTIC_EXECUTOR_BLOCKER_REASONS.sourceArtifactDigestMismatch],
    });
  });

  it('fails closed when artifact bytes are not canonical ppux-rgba8 bytes', async () => {
    await expect(deterministicExactCompositeExecutor.execute({
      plan: planWith(),
      source: { ...sourceArtifact, bytes: new Uint8Array([1, 2, 3]) },
      assets: [],
    })).rejects.toMatchObject({
      blocker_reasons: [DETERMINISTIC_EXECUTOR_BLOCKER_REASONS.sourceArtifactBytesInvalid],
    });
  });

  it('keeps unsupported inset fail-closed rather than inventing source geometry', async () => {
    const plan = planWith({
      overlays: [{
        overlay_id: 'inset-1',
        kind: 'inset',
        bounds: { space: RECT_SPACES.outputPixel, rect: [20, 2, 8, 8] },
        source_rect: { space: RECT_SPACES.sourcePixel, rect: [8, 4, 4, 4] },
        magnification: 2,
      }],
    });

    await expect(deterministicExactCompositeExecutor.execute({ plan, source: sourceArtifact, assets: [] }))
      .rejects.toMatchObject({ blocker_reasons: [DETERMINISTIC_EXECUTOR_BLOCKER_REASONS.unsupportedInset] });
  });

  it('produces corruption that the independent pixel gate rejects', async () => {
    const plan = planWith();
    const output = await deterministicExactCompositeExecutor.execute({ plan, source: sourceArtifact, assets: [] });
    const corrupted = artifactToImage(output.image);
    setPixel(corrupted, 0, 0, [255, 0, 255, 1]);

    expect(validatePixelFidelity({ plan, source: sourceImage, output: corrupted }).passed).toBe(false);
  });

  it('uses the typed execution error for blocked requests', async () => {
    await expect(deterministicExactCompositeExecutor.execute({
      plan: planWith({ scale_x: 2, scale_y: 2 }),
      source: sourceArtifact,
      assets: [],
    })).rejects.toBeInstanceOf(DeterministicExactCompositeExecutionError);
  });
});
