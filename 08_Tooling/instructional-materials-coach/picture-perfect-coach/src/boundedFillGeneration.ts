import type { CaptureStatus } from './captureEvidence';
import { imageSha256, type RgbaImage } from './exactCompositePrimitives';
import type { OutputPixelRect } from './framePlan';
import {
  admitReferenceRegions,
  type ApprovedVisualReference,
  type ReferenceRegion,
  type ReferenceRegionSet,
  type VisualReferenceBlockerReason,
} from './visualReference';

/**
 * PPUX-VRL11 (#1497) provider-neutral bounded generated-fill contract.
 *
 * This module never calls a provider. It admits one explicit generation intent
 * against one already-approved #1485 fill region, then mechanically validates a
 * returned patch before deterministic composition. Provider identity, price,
 * vendor syntax, OCR/CV, and semantic model scoring are deliberately absent.
 */

export const BOUNDED_FILL_BLOCKER_REASONS = {
  fillRegionMissing: 'bounded-fill-region-missing',
  fillRegionNotAllowed: 'bounded-fill-region-not-allowed',
  generationIntentMissing: 'bounded-fill-generation-intent-missing',
  exactContentRequired: 'bounded-fill-exact-content-required',
  patchMissing: 'bounded-fill-patch-missing',
  patchDimensionsMismatch: 'bounded-fill-patch-dimensions-mismatch',
  patchIdentityMismatch: 'bounded-fill-patch-identity-mismatch',
  patchCopyThrough: 'bounded-fill-patch-copy-through',
  patchEscapesRegion: 'bounded-fill-patch-escapes-region',
  sourceDimensionsInvalid: 'bounded-fill-source-dimensions-invalid',
} as const;

export type BoundedFillBlockerReason =
  (typeof BOUNDED_FILL_BLOCKER_REASONS)[keyof typeof BOUNDED_FILL_BLOCKER_REASONS];

export type BoundedFillBlocker = BoundedFillBlockerReason | VisualReferenceBlockerReason;

export type BoundedFillIntent = Readonly<{
  fill_id: string;
  region_id: string;
  prompt: string;
  fill_required: boolean;
  /** Exact UI/text/CAD/source-pixel requirements remain outside generation. */
  exact_content_required: boolean;
}>;

export type BoundedFillPlan = Readonly<{
  fill_id: string;
  reference_id: string;
  content_fingerprint: string;
  region_id: string;
  destination: OutputPixelRect;
  prompt: string;
  fill_required: boolean;
  execution_authorized: false;
}>;

export type BoundedFillAdmissionResult = Readonly<{
  status: CaptureStatus;
  plan: BoundedFillPlan | null;
  blocker_reasons: readonly BoundedFillBlocker[];
}>;

function validDimension(value: number): boolean {
  return Number.isInteger(value) && value > 0;
}

function regionDestination(region: ReferenceRegion, width: number, height: number): OutputPixelRect {
  const [x, y, regionWidth, regionHeight] = region.rect;
  const left = Math.round(x * width);
  const top = Math.round(y * height);
  const right = Math.round((x + regionWidth) * width);
  const bottom = Math.round((y + regionHeight) * height);
  return {
    space: 'output-pixel',
    rect: [left, top, right - left, bottom - top],
  };
}

export function admitBoundedFill(
  reference: ApprovedVisualReference,
  regionSet: ReferenceRegionSet,
  intent: BoundedFillIntent,
  outputWidthPx: number,
  outputHeightPx: number,
): BoundedFillAdmissionResult {
  const regionAdmission = admitReferenceRegions(reference, regionSet);
  if (regionAdmission.status !== 'valid' || !regionAdmission.regions) {
    return { status: regionAdmission.status, plan: null, blocker_reasons: regionAdmission.blocker_reasons };
  }
  if (!validDimension(outputWidthPx) || !validDimension(outputHeightPx)) {
    return { status: 'blocked', plan: null, blocker_reasons: [BOUNDED_FILL_BLOCKER_REASONS.sourceDimensionsInvalid] };
  }

  const region = regionAdmission.regions.find((candidate) => candidate.region_id === intent.region_id);
  if (!region) {
    return { status: 'blocked', plan: null, blocker_reasons: [BOUNDED_FILL_BLOCKER_REASONS.fillRegionMissing] };
  }
  if (!region.fill_allowed) {
    return { status: 'blocked', plan: null, blocker_reasons: [BOUNDED_FILL_BLOCKER_REASONS.fillRegionNotAllowed] };
  }
  if (!intent.prompt.trim()) {
    return { status: 'blocked', plan: null, blocker_reasons: [BOUNDED_FILL_BLOCKER_REASONS.generationIntentMissing] };
  }
  if (intent.exact_content_required) {
    return { status: 'blocked', plan: null, blocker_reasons: [BOUNDED_FILL_BLOCKER_REASONS.exactContentRequired] };
  }

  return {
    status: 'valid',
    blocker_reasons: [],
    plan: Object.freeze({
      fill_id: intent.fill_id,
      reference_id: reference.reference_id,
      content_fingerprint: reference.asset_reference.content_fingerprint,
      region_id: region.region_id,
      destination: regionDestination(region, outputWidthPx, outputHeightPx),
      prompt: intent.prompt.trim(),
      fill_required: intent.fill_required,
      execution_authorized: false,
    }),
  };
}

export type GeneratedPatch = Readonly<{
  fill_id: string;
  image: RgbaImage;
  sha256: string;
}>;

export type GeneratedPatchValidationResult = Readonly<{
  status: CaptureStatus;
  blocker_reasons: readonly BoundedFillBlockerReason[];
}>;

function cropRegion(source: RgbaImage, rect: readonly [number, number, number, number]): RgbaImage {
  const [left, top, width, height] = rect;
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const sourceOffset = ((top + y) * source.width + left + x) * 4;
      const targetOffset = (y * width + x) * 4;
      data.set(source.data.slice(sourceOffset, sourceOffset + 4), targetOffset);
    }
  }
  return { width, height, data };
}

export function validateGeneratedPatch(
  plan: BoundedFillPlan,
  source: RgbaImage,
  patch: GeneratedPatch | null,
): GeneratedPatchValidationResult {
  if (!patch) {
    return { status: 'blocked', blocker_reasons: [BOUNDED_FILL_BLOCKER_REASONS.patchMissing] };
  }
  const [, , width, height] = plan.destination.rect;
  if (patch.fill_id !== plan.fill_id || patch.sha256 !== imageSha256(patch.image)) {
    return { status: 'blocked', blocker_reasons: [BOUNDED_FILL_BLOCKER_REASONS.patchIdentityMismatch] };
  }
  if (patch.image.width !== width || patch.image.height !== height) {
    return { status: 'blocked', blocker_reasons: [BOUNDED_FILL_BLOCKER_REASONS.patchDimensionsMismatch] };
  }
  const [left, top] = plan.destination.rect;
  if (left < 0 || top < 0 || left + width > source.width || top + height > source.height) {
    return { status: 'blocked', blocker_reasons: [BOUNDED_FILL_BLOCKER_REASONS.patchEscapesRegion] };
  }
  if (plan.fill_required && imageSha256(cropRegion(source, plan.destination.rect)) === patch.sha256) {
    return { status: 'blocked', blocker_reasons: [BOUNDED_FILL_BLOCKER_REASONS.patchCopyThrough] };
  }
  return { status: 'valid', blocker_reasons: [] };
}

/**
 * Compose only after mechanical validation. Pixels outside `destination` are
 * copied byte-for-byte from source; the patch cannot resize, feather, or bleed.
 */
export function composeGeneratedPatch(
  plan: BoundedFillPlan,
  source: RgbaImage,
  patch: GeneratedPatch,
): RgbaImage {
  const validation = validateGeneratedPatch(plan, source, patch);
  if (validation.status !== 'valid') throw new RangeError(validation.blocker_reasons.join(','));

  const output = { width: source.width, height: source.height, data: new Uint8ClampedArray(source.data) };
  const [left, top, width, height] = plan.destination.rect;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const sourceOffset = (y * width + x) * 4;
      const targetOffset = ((top + y) * output.width + left + x) * 4;
      output.data.set(patch.image.data.slice(sourceOffset, sourceOffset + 4), targetOffset);
    }
  }
  return output;
}
