import type { CaptureStatus } from '../captureEvidence';
import {
  EXECUTOR_PROVENANCE_REPORT_VERSION,
  admitExecutionRequest,
  type ApprovedExactAsset,
  type ExactCompositeArtifact,
  type ExecutedAssetPlacement,
  type ExecutedOverlayMask,
  type ExecutedSpotlightRecord,
  type ExecutorBlockerReason,
  type ExecutorProvenanceReport,
} from '../executorContract';
import type { RectXywh, TutorialFramePlan } from '../framePlan';
import {
  cropImage,
  dimImage,
  fillRect,
  getPixel,
  imageArtifactBytes,
  imageSha256,
  placeAsset,
  planSha256,
  scaleImage,
  setPixel,
  type RgbaImage,
  type SpotlightSpec,
} from '../exactCompositePrimitives';

/**
 * PPUX-VRL7 (#1484) fixture reference renderer.
 *
 * This is a test and reference implementation, not a second production
 * executor. Its only job is to produce a trusted known-good source/output pair
 * so the independent validator can be proven to accept a clean frame and reject
 * corrupted ones before any external executor is trusted with real work.
 *
 * It composites in the order the validator forward-constructs its expected
 * image -- crop, declared resampler, asset placement, dim in the declared
 * colour space -- and only then paints overlays, which the validator excludes.
 * Overlays are painted as flat blocks from the plan's own constants: the
 * fixture does not need to be a faithful annotation renderer, because those
 * rects are exactly the ones the exclusion mask removes from comparison.
 */

export type FixtureRenderResult = Readonly<{
  status: CaptureStatus;
  image: RgbaImage | null;
  report: ExecutorProvenanceReport | null;
  blocker_reasons: readonly ExecutorBlockerReason[];
}>;

export function toArtifact(image: RgbaImage): ExactCompositeArtifact {
  return {
    sha256: imageSha256(image),
    width_px: image.width,
    height_px: image.height,
    bytes: imageArtifactBytes(image),
  };
}

/**
 * A deterministic synthetic source. Every channel is a fixed function of its
 * coordinates, so the same dimensions always produce byte-identical pixels and
 * no private or classroom capture is ever required for a fixture.
 */
export function createFixtureSource(width: number, height: number): RgbaImage {
  const image: RgbaImage = { width, height, data: new Uint8ClampedArray(width * height * 4) };
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      setPixel(image, x, y, [
        (x * 7 + 40) % 256,
        (y * 11 + 80) % 256,
        (x * 3 + y * 5 + 120) % 256,
        1,
      ]);
    }
  }
  return image;
}

function spotlightFromPlan(plan: TutorialFramePlan): { spec: SpotlightSpec; record: ExecutedSpotlightRecord } | null {
  for (const overlay of plan.overlays) {
    if (overlay.kind !== 'spotlight') continue;
    return {
      spec: {
        boundary: overlay.boundary.rect,
        falloff_px: overlay.falloff_px,
        falloff_function: overlay.falloff_function,
      },
      record: {
        overlay_id: overlay.overlay_id,
        boundary: overlay.boundary,
        padding_px: overlay.padding_px,
        falloff_px: overlay.falloff_px,
        falloff_function: overlay.falloff_function,
      },
    };
  }
  return null;
}

function paintOverlays(image: RgbaImage, plan: TutorialFramePlan): ExecutedOverlayMask[] {
  const masks: ExecutedOverlayMask[] = [];
  for (const overlay of plan.overlays) {
    masks.push({ overlay_id: overlay.overlay_id, kind: overlay.kind, bounds: overlay.bounds });
    if (overlay.kind === 'spotlight') continue;
    const colour = overlay.kind === 'badge'
      ? plan.render_spec.badge.fill_rgba
      : overlay.kind === 'arrow'
        ? plan.render_spec.arrow.rgba
        : plan.render_spec.label.background_rgba;
    fillRect(image, overlay.bounds.rect, colour);
  }
  return masks;
}

/**
 * Render one exact-composite frame and its provenance.
 *
 * The request is admitted through the Stage 4 executor contract first, so an
 * incomplete plan fails closed here exactly as it would for a real executor.
 * Every digest in the report is computed from the artifact that was actually
 * produced, never asserted.
 */
export function renderExactCompositeFixture(
  plan: TutorialFramePlan,
  source: RgbaImage,
  assets: ReadonlyMap<string, RgbaImage> = new Map(),
): FixtureRenderResult {
  const sourceArtifact = toArtifact(source);
  const suppliedAssets: ApprovedExactAsset[] = plan.asset_fills.flatMap((fill) => {
    const asset = assets.get(fill.asset_id);
    if (!asset) return [];
    return [{ asset_id: fill.asset_id, asset_fingerprint: fill.asset_fingerprint, artifact: toArtifact(asset) }];
  });

  const admission = admitExecutionRequest({ plan, source: sourceArtifact, assets: suppliedAssets });
  if (admission.status !== 'valid') {
    return { status: admission.status, image: null, report: null, blocker_reasons: admission.blocker_reasons };
  }

  const cropped = cropImage(source, plan.source_rect.rect);
  const scaled = scaleImage(cropped, plan.output_width_px, plan.output_height_px, plan.render_spec.resampler);

  const placements: ExecutedAssetPlacement[] = [];
  for (const fill of plan.asset_fills) {
    const asset = assets.get(fill.asset_id)!;
    placeAsset(scaled, asset, fill.destination.rect);
    placements.push({
      fill_id: fill.fill_id,
      asset_id: fill.asset_id,
      asset_fingerprint: fill.asset_fingerprint,
      destination: fill.destination,
    });
  }

  const spotlight = spotlightFromPlan(plan);
  const dimmed = dimImage(
    scaled,
    plan.render_spec.dim_rgba,
    plan.render_spec.compositing_colour_space,
    spotlight?.spec ?? null,
  );
  const overlayMasks = paintOverlays(dimmed, plan);

  return {
    status: 'valid',
    image: dimmed,
    blocker_reasons: [],
    report: {
      report_version: EXECUTOR_PROVENANCE_REPORT_VERSION,
      rect_convention: plan.rect_convention,
      source_sha256: sourceArtifact.sha256,
      source_width_px: source.width,
      source_height_px: source.height,
      plan_sha256: planSha256(plan),
      output_sha256: imageSha256(dimmed),
      output_width_px: dimmed.width,
      output_height_px: dimmed.height,
      source_rect: plan.source_rect,
      scale_x: plan.scale_x,
      scale_y: plan.scale_y,
      resampler: plan.render_spec.resampler,
      compositing_colour_space: plan.render_spec.compositing_colour_space,
      render_mode: plan.render_mode,
      generation_used: false,
      executed_dim_rgba: plan.render_spec.dim_rgba,
      executed_spotlight: spotlight?.record ?? null,
      overlay_masks: overlayMasks,
      overlay_bleed_px: plan.render_spec.overlay_bleed_px,
      asset_placements: placements,
      diagnostics: {
        executor_id: 'ppux-fixture-reference-renderer',
        executor_version: '1',
        narrative: null,
        elapsed_ms: null,
        step_trace: null,
        recovered_spotlight_estimate: null,
      },
    },
  };
}

/* --------------------------- corruption fixtures --------------------------- */

function copyOf(image: RgbaImage): RgbaImage {
  return { width: image.width, height: image.height, data: new Uint8ClampedArray(image.data) };
}

/** A small opaque repaint, as a localized redraw of interface detail would be. */
export function withLocalizedRedraw(image: RgbaImage, rect: RectXywh): RgbaImage {
  const corrupted = copyOf(image);
  fillRect(corrupted, rect, [255, 0, 255, 1]);
  return corrupted;
}

/** A uniform channel shift, as a regrade or wrong colour transform would be. */
export function withGlobalTint(image: RgbaImage, delta: number): RgbaImage {
  const corrupted = copyOf(image);
  for (let y = 0; y < image.height; y += 1) {
    for (let x = 0; x < image.width; x += 1) {
      const [r, g, b, a] = getPixel(image, x, y);
      setPixel(corrupted, x, y, [r + delta, g + delta, b + delta, a]);
    }
  }
  return corrupted;
}

/**
 * Low-amplitude edits spread over many pixels: individually below a naive
 * per-pixel threshold, collectively a real difference. This is the case a
 * maximum-error-only comparison misses.
 */
export function withDiffuseLowLevelEdit(image: RgbaImage, amplitude: number): RgbaImage {
  const corrupted = copyOf(image);
  for (let y = 0; y < image.height; y += 1) {
    for (let x = 0; x < image.width; x += 1) {
      const [r, g, b, a] = getPixel(image, x, y);
      const shift = (x + y) % 2 === 0 ? amplitude : -amplitude;
      setPixel(corrupted, x, y, [r + shift, g + shift, b + shift, a]);
    }
  }
  return corrupted;
}

/** Channel quantization, standing in for a lossy re-encode of a native artifact. */
export function withLossyRequantization(image: RgbaImage, step: number): RgbaImage {
  const corrupted = copyOf(image);
  for (let y = 0; y < image.height; y += 1) {
    for (let x = 0; x < image.width; x += 1) {
      const [r, g, b, a] = getPixel(image, x, y);
      const quantize = (channel: number): number => Math.round(channel / step) * step;
      setPixel(corrupted, x, y, [quantize(r), quantize(g), quantize(b), a]);
    }
  }
  return corrupted;
}
