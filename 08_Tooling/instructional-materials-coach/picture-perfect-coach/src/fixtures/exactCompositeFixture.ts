import type { CaptureStatus } from '../captureEvidence';
import type { ExactCompositeArtifact, ExecutorBlockerReason, ExecutorProvenanceReport } from '../executorContract';
import type { RectXywh, TutorialFramePlan } from '../framePlan';
import {
  renderDeterministicExactComposite,
  toExactCompositeArtifact,
} from '../exactCompositeExecutor';
import {
  fillRect,
  getPixel,
  setPixel,
  type RgbaImage,
} from '../exactCompositePrimitives';

/**
 * PPUX-VRL7 (#1484) trusted fixture adapter.
 *
 * #2075 deliberately keeps this as a fixture/reference surface rather than a
 * second compositor. Rendering delegates to the single deterministic production
 * core; this module only supplies synthetic fixture pixels and corruption cases
 * for the independent validators.
 */
export type FixtureRenderResult = Readonly<{
  status: CaptureStatus;
  image: RgbaImage | null;
  report: ExecutorProvenanceReport | null;
  blocker_reasons: readonly ExecutorBlockerReason[];
}>;

export function toArtifact(image: RgbaImage): ExactCompositeArtifact {
  return toExactCompositeArtifact(image);
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

/**
 * Render one trusted fixture frame through the same raster/provenance core used
 * by the production executor. The fixture keeps a distinct diagnostic identity
 * but owns no rendering arithmetic of its own.
 */
export function renderExactCompositeFixture(
  plan: TutorialFramePlan,
  source: RgbaImage,
  assets: ReadonlyMap<string, RgbaImage> = new Map(),
): FixtureRenderResult {
  return renderDeterministicExactComposite(plan, source, assets, {
    executor_id: 'ppux-fixture-reference-renderer',
    executor_version: '2',
  }) as FixtureRenderResult;
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
