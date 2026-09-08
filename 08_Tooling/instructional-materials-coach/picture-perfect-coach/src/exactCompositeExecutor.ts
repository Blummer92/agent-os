import type { CaptureStatus } from './captureEvidence';
import {
  EXECUTOR_PROVENANCE_REPORT_VERSION,
  admitExecutionRequest,
  type ExactCompositeArtifact,
  type ExactCompositeExecutionRequest,
  type ExactCompositeExecutionOutput,
  type ExactCompositeExecutor,
  type ExecutedAssetPlacement,
  type ExecutedOverlayMask,
  type ExecutedSpotlightRecord,
  type ExecutorBlockerReason,
  type ExecutorProvenanceReport,
} from './executorContract';
import type { TutorialFramePlan } from './framePlan';
import {
  cropImage,
  dimImage,
  fillRect,
  imageArtifactBytes,
  imageSha256,
  placeAsset,
  planSha256,
  scaleImage,
  sha256Hex,
  utf8Bytes,
  type RgbaImage,
  type SpotlightSpec,
} from './exactCompositePrimitives';

export const DETERMINISTIC_EXACT_COMPOSITE_EXECUTOR_ID = 'ppux-deterministic-exact-composite-executor' as const;
export const DETERMINISTIC_EXACT_COMPOSITE_EXECUTOR_VERSION = '1' as const;

export const DETERMINISTIC_EXECUTOR_BLOCKER_REASONS = {
  sourceArtifactBytesInvalid: 'executor-source-artifact-bytes-invalid',
  sourceArtifactDigestMismatch: 'executor-source-artifact-digest-mismatch',
  assetArtifactBytesInvalid: 'executor-asset-artifact-bytes-invalid',
  assetArtifactDigestMismatch: 'executor-asset-artifact-digest-mismatch',
  unsupportedInset: 'executor-inset-unsupported',
} as const;

export type DeterministicExecutorBlockerReason =
  | ExecutorBlockerReason
  | (typeof DETERMINISTIC_EXECUTOR_BLOCKER_REASONS)[keyof typeof DETERMINISTIC_EXECUTOR_BLOCKER_REASONS];

export class DeterministicExactCompositeExecutionError extends Error {
  readonly blocker_reasons: readonly DeterministicExecutorBlockerReason[];

  constructor(blockerReasons: readonly DeterministicExecutorBlockerReason[]) {
    super(`deterministic exact-composite execution blocked: ${blockerReasons.join(', ')}`);
    this.name = 'DeterministicExactCompositeExecutionError';
    this.blocker_reasons = [...blockerReasons];
  }
}

export type DeterministicRenderResult = Readonly<{
  status: CaptureStatus;
  image: RgbaImage | null;
  report: ExecutorProvenanceReport | null;
  blocker_reasons: readonly DeterministicExecutorBlockerReason[];
}>;

export type DeterministicRenderDiagnostics = Readonly<{
  executor_id: string;
  executor_version: string;
}>;

const DEFAULT_DIAGNOSTICS: DeterministicRenderDiagnostics = Object.freeze({
  executor_id: DETERMINISTIC_EXACT_COMPOSITE_EXECUTOR_ID,
  executor_version: DETERMINISTIC_EXACT_COMPOSITE_EXECUTOR_VERSION,
});

export function toExactCompositeArtifact(image: RgbaImage): ExactCompositeArtifact {
  return {
    sha256: imageSha256(image),
    width_px: image.width,
    height_px: image.height,
    bytes: imageArtifactBytes(image),
  };
}

function bytesEqual(left: Uint8Array, right: Uint8Array): boolean {
  if (left.length !== right.length) return false;
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) return false;
  }
  return true;
}

function decodeExactCompositeArtifact(
  artifact: ExactCompositeArtifact,
  invalidBytesReason: DeterministicExecutorBlockerReason,
  digestMismatchReason: DeterministicExecutorBlockerReason,
): RgbaImage {
  const header = utf8Bytes(`ppux-rgba8:${artifact.width_px}x${artifact.height_px}:`);
  const expectedLength = header.length + artifact.width_px * artifact.height_px * 4;
  if (artifact.bytes.length !== expectedLength || !bytesEqual(artifact.bytes.subarray(0, header.length), header)) {
    throw new DeterministicExactCompositeExecutionError([invalidBytesReason]);
  }
  if (sha256Hex(artifact.bytes) !== artifact.sha256) {
    throw new DeterministicExactCompositeExecutionError([digestMismatchReason]);
  }

  const rgba = artifact.bytes.subarray(header.length);
  const data = new Uint8ClampedArray(rgba.length);
  data.set(rgba);
  return { width: artifact.width_px, height: artifact.height_px, data };
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

function paintPlanAuthorizedOverlays(image: RgbaImage, plan: TutorialFramePlan): ExecutedOverlayMask[] {
  const masks: ExecutedOverlayMask[] = [];
  for (const overlay of plan.overlays) {
    masks.push({ overlay_id: overlay.overlay_id, kind: overlay.kind, bounds: overlay.bounds });
    if (overlay.kind === 'spotlight') continue;
    if (overlay.kind === 'inset') {
      throw new DeterministicExactCompositeExecutionError([
        DETERMINISTIC_EXECUTOR_BLOCKER_REASONS.unsupportedInset,
      ]);
    }
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
 * Single deterministic raster/provenance core for both production execution and
 * the trusted fixture adapter. It consumes only the resolved plan and exact
 * decoded artifacts; there is no discovery, provider call, or inferred state.
 */
export function renderDeterministicExactComposite(
  plan: TutorialFramePlan,
  source: RgbaImage,
  assets: ReadonlyMap<string, RgbaImage> = new Map(),
  diagnostics: DeterministicRenderDiagnostics = DEFAULT_DIAGNOSTICS,
): DeterministicRenderResult {
  const sourceArtifact = toExactCompositeArtifact(source);
  const suppliedAssets = plan.asset_fills.flatMap((fill) => {
    const asset = assets.get(fill.asset_id);
    if (!asset) return [];
    return [{
      asset_id: fill.asset_id,
      asset_fingerprint: fill.asset_fingerprint,
      artifact: toExactCompositeArtifact(asset),
    }];
  });

  const admission = admitExecutionRequest({ plan, source: sourceArtifact, assets: suppliedAssets });
  if (admission.status !== 'valid') {
    return { status: admission.status, image: null, report: null, blocker_reasons: admission.blocker_reasons };
  }

  try {
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
    const overlayMasks = paintPlanAuthorizedOverlays(dimmed, plan);

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
          executor_id: diagnostics.executor_id,
          executor_version: diagnostics.executor_version,
          narrative: null,
          elapsed_ms: null,
          step_trace: null,
          recovered_spotlight_estimate: null,
        },
      },
    };
  } catch (error) {
    if (error instanceof DeterministicExactCompositeExecutionError) {
      return { status: 'blocked', image: null, report: null, blocker_reasons: error.blocker_reasons };
    }
    throw error;
  }
}

function decodeExecutionRequest(request: ExactCompositeExecutionRequest): {
  source: RgbaImage;
  assets: ReadonlyMap<string, RgbaImage>;
} {
  const source = decodeExactCompositeArtifact(
    request.source,
    DETERMINISTIC_EXECUTOR_BLOCKER_REASONS.sourceArtifactBytesInvalid,
    DETERMINISTIC_EXECUTOR_BLOCKER_REASONS.sourceArtifactDigestMismatch,
  );
  const assets = new Map<string, RgbaImage>();
  for (const asset of request.assets) {
    assets.set(asset.asset_id, decodeExactCompositeArtifact(
      asset.artifact,
      DETERMINISTIC_EXECUTOR_BLOCKER_REASONS.assetArtifactBytesInvalid,
      DETERMINISTIC_EXECUTOR_BLOCKER_REASONS.assetArtifactDigestMismatch,
    ));
  }
  return { source, assets };
}

async function executeDeterministically(request: ExactCompositeExecutionRequest): Promise<ExactCompositeExecutionOutput> {
  const admission = admitExecutionRequest(request);
  if (admission.status !== 'valid') {
    throw new DeterministicExactCompositeExecutionError(admission.blocker_reasons);
  }

  const decoded = decodeExecutionRequest(request);
  const result = renderDeterministicExactComposite(request.plan, decoded.source, decoded.assets);
  if (result.status !== 'valid' || !result.image || !result.report) {
    throw new DeterministicExactCompositeExecutionError(result.blocker_reasons);
  }

  return { image: toExactCompositeArtifact(result.image), report: result.report };
}

/** The one production repository implementation selected by #1792/#2075. */
export const deterministicExactCompositeExecutor: ExactCompositeExecutor = Object.freeze({
  execute: executeDeterministically,
});
