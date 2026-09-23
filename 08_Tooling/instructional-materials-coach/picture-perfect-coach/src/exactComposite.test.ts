import { describe, expect, it } from 'vitest';
import {
  canonicalJson,
  createImage,
  cropImage,
  dimImage,
  getPixel,
  imageSha256,
  placeAsset,
  planSha256,
  scaleImage,
  setPixel,
  sha256Hex,
  utf8Bytes,
  type RgbaImage,
} from './exactCompositePrimitives';
import {
  createFixtureSource,
  renderExactCompositeFixture,
  withDiffuseLowLevelEdit,
  withGlobalTint,
  withLocalizedRedraw,
  withLossyRequantization,
} from './fixtures/exactCompositeFixture';
import {
  DEFAULT_EXACT_COMPOSITE_RENDER_SPEC,
  RECT_CONVENTION,
  RECT_SPACES,
  RENDER_MODES,
  TUTORIAL_FRAME_PLAN_VERSION,
  type TutorialFramePlan,
} from './framePlan';
import { EXECUTOR_BLOCKER_REASONS } from './executorContract';

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
    overlays: [
      {
        overlay_id: 'spotlight-1',
        kind: 'spotlight',
        bounds: { space: RECT_SPACES.outputPixel, rect: [6, 2, 16, 12] },
        region_id: 'add-content-button',
        boundary: { space: RECT_SPACES.outputPixel, rect: [8, 4, 12, 8] },
        padding_px: 2,
        falloff_px: 2,
        falloff_function: 'smoothstep',
      },
      {
        overlay_id: 'badge-1',
        kind: 'badge',
        bounds: { space: RECT_SPACES.outputPixel, rect: [24, 6, 6, 6] },
        ordinal: 1,
        centre_x_px: 27,
        centre_y_px: 9,
      },
    ],
    anchored_rects: [{ region_id: 'add-content-button', rect: { space: RECT_SPACES.outputPixel, rect: [8, 4, 12, 8] } }],
    must_show_region_ids: ['add-content-button'],
    annotation_intent: { target_region_id: 'add-content-button', label: 'Add content', preferred_side: 'right' },
    execution_authorized: false,
    ...overrides,
  };
}

const source = createFixtureSource(64, 36);

describe('artifact identity', () => {
  it('computes SHA-256 matching the published vectors', () => {
    expect(sha256Hex(utf8Bytes(''))).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
    expect(sha256Hex(utf8Bytes('abc'))).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  });

  it('canonicalizes JSON independently of key order', () => {
    expect(canonicalJson({ b: 1, a: [3, { d: 4, c: 5 }] })).toBe('{"a":[3,{"c":5,"d":4}],"b":1}');
    expect(planSha256({ x: 1, y: 2 })).toBe(planSha256({ y: 2, x: 1 }));
  });

  it('binds image dimensions into the digest', () => {
    const wide: RgbaImage = { width: 4, height: 1, data: new Uint8ClampedArray(16).fill(9) };
    const square: RgbaImage = { width: 2, height: 2, data: new Uint8ClampedArray(16).fill(9) };

    expect(wide.data).toEqual(square.data);
    expect(imageSha256(wide)).not.toBe(imageSha256(square));
  });
});

describe('deterministic image primitives', () => {
  it('crops exact source pixels', () => {
    const cropped = cropImage(source, [4, 2, 3, 2]);

    expect(cropped.width).toBe(3);
    expect(getPixel(cropped, 0, 0)).toEqual(getPixel(source, 4, 2));
    expect(getPixel(cropped, 2, 1)).toEqual(getPixel(source, 6, 3));
  });

  it('refuses to resample when the plan declares no resampler', () => {
    expect(() => scaleImage(source, 32, 18, 'none')).toThrow(RangeError);
    expect(scaleImage(source, 64, 36, 'none').data).toEqual(source.data);
  });

  it('doubles pixels exactly under integer nearest scale', () => {
    const small = createImage(2, 1, [10, 20, 30, 1]);
    setPixel(small, 1, 0, [200, 100, 50, 1]);
    const doubled = scaleImage(small, 4, 2, 'nearest');

    expect(getPixel(doubled, 0, 0)).toEqual([10, 20, 30, 1]);
    expect(getPixel(doubled, 1, 1)).toEqual([10, 20, 30, 1]);
    expect(getPixel(doubled, 3, 0)).toEqual([200, 100, 50, 1]);
  });

  it('dims in the declared colour space, and the space changes the pixels', () => {
    const flat = createImage(1, 1, [200, 200, 200, 1]);
    const srgb = dimImage(flat, [0, 0, 0, 0.5], 'srgb');
    const linear = dimImage(flat, [0, 0, 0, 0.5], 'linear');

    expect(getPixel(srgb, 0, 0)[0]).toBe(100);
    expect(getPixel(linear, 0, 0)[0]).not.toBe(100);
  });

  it('holds the spotlight open and ramps across the declared falloff', () => {
    const flat = createImage(16, 1, [200, 200, 200, 1]);
    const spotlit = dimImage(flat, [0, 0, 0, 0.5], 'srgb', {
      boundary: [4, 0, 4, 1],
      falloff_px: 3,
      falloff_function: 'linear',
    });

    expect(getPixel(spotlit, 5, 0)[0]).toBe(200);
    expect(getPixel(spotlit, 15, 0)[0]).toBe(100);
    const ramp = [8, 9, 10].map((x) => getPixel(spotlit, x, 0)[0]);
    expect(ramp[0]!).toBeGreaterThan(ramp[1]!);
    expect(ramp[1]!).toBeGreaterThan(ramp[2]!);
  });

  it('places an approved asset by copying its pixels', () => {
    const target = createImage(8, 8, [0, 0, 0, 1]);
    const asset = createImage(2, 2, [7, 8, 9, 1]);
    placeAsset(target, asset, [3, 3, 2, 2]);

    expect(getPixel(target, 3, 3)).toEqual([7, 8, 9, 1]);
    expect(getPixel(target, 5, 5)).toEqual([0, 0, 0, 1]);
  });
});

describe('fixture reference renderer', () => {
  it('renders a frame whose report digests bind to the artifacts produced', () => {
    const plan = planWith();
    const result = renderExactCompositeFixture(plan, source);

    expect(result.status).toBe('valid');
    expect(result.image?.width).toBe(32);
    expect(result.report?.output_sha256).toBe(imageSha256(result.image!));
    expect(result.report?.source_sha256).toBe(imageSha256(source));
    expect(result.report?.plan_sha256).toBe(planSha256(plan));
    expect(result.report?.generation_used).toBe(false);
  });

  it('is byte-for-byte deterministic', () => {
    const first = renderExactCompositeFixture(planWith(), source);
    const second = renderExactCompositeFixture(planWith(), source);

    expect(first.report?.output_sha256).toBe(second.report?.output_sha256);
    expect(Array.from(first.image!.data)).toEqual(Array.from(second.image!.data));
  });

  it('records the executed spotlight and every overlay mask', () => {
    const result = renderExactCompositeFixture(planWith(), source);

    expect(result.report?.executed_spotlight?.overlay_id).toBe('spotlight-1');
    expect(result.report?.executed_spotlight?.falloff_function).toBe('smoothstep');
    expect(result.report?.overlay_masks.map((mask) => mask.overlay_id)).toEqual(['spotlight-1', 'badge-1']);
    expect(result.report?.overlay_bleed_px).toBe(DEFAULT_EXACT_COMPOSITE_RENDER_SPEC.overlay_bleed_px);
  });

  it('keeps spotlit source pixels and dims outside the boundary', () => {
    const result = renderExactCompositeFixture(planWith(), source);

    expect(getPixel(result.image!, 10, 6)).toEqual(getPixel(source, 10, 6));
    expect(getPixel(result.image!, 0, 0)[0]).not.toBe(getPixel(source, 0, 0)[0]);
  });

  it('places an approved asset and records its fingerprint', () => {
    const plan = planWith({
      asset_fills: [{
        fill_id: 'fill-1',
        asset_id: 'callout',
        asset_fingerprint: 'sha256:callout',
        destination: { space: RECT_SPACES.outputPixel, rect: [10, 5, 2, 2] },
      }],
    });
    const assets = new Map([['callout', createImage(2, 2, [1, 2, 3, 1])]]);
    const result = renderExactCompositeFixture(plan, source, assets);

    expect(result.status).toBe('valid');
    expect(getPixel(result.image!, 10, 5)).toEqual([1, 2, 3, 1]);
    expect(result.report?.asset_placements).toEqual([{
      fill_id: 'fill-1',
      asset_id: 'callout',
      asset_fingerprint: 'sha256:callout',
      destination: { space: 'output-pixel', rect: [10, 5, 2, 2] },
    }]);
  });

  it('fails closed on an incomplete plan instead of rendering', () => {
    const result = renderExactCompositeFixture(planWith({ scale_x: 2, scale_y: 2 }), source);

    expect(result.status).toBe('blocked');
    expect(result.image).toBeNull();
    expect(result.report).toBeNull();
    expect(result.blocker_reasons).toContain(EXECUTOR_BLOCKER_REASONS.scaleInconsistent);
  });
});

describe('corruption fixtures', () => {
  const clean = renderExactCompositeFixture(planWith(), source).image!;

  it('confines a localized redraw to its rect', () => {
    const corrupted = withLocalizedRedraw(clean, [2, 2, 3, 3]);

    expect(getPixel(corrupted, 3, 3)).toEqual([255, 0, 255, 1]);
    expect(getPixel(corrupted, 20, 15)).toEqual(getPixel(clean, 20, 15));
  });

  it('shifts every pixel under a global tint', () => {
    const corrupted = withGlobalTint(clean, 6);

    for (const [x, y] of [[0, 0], [10, 6], [31, 17]] as const) {
      expect(getPixel(corrupted, x, y)[0]).toBe(Math.min(255, getPixel(clean, x, y)[0] + 6));
    }
  });

  it('spreads a diffuse edit at low per-pixel amplitude', () => {
    const corrupted = withDiffuseLowLevelEdit(clean, 2);
    let changed = 0;
    let maximum = 0;
    for (let y = 0; y < clean.height; y += 1) {
      for (let x = 0; x < clean.width; x += 1) {
        const difference = Math.abs(getPixel(corrupted, x, y)[0] - getPixel(clean, x, y)[0]);
        if (difference > 0) changed += 1;
        maximum = Math.max(maximum, difference);
      }
    }

    expect(changed).toBeGreaterThan(clean.width * clean.height * 0.5);
    expect(maximum).toBeLessThanOrEqual(2);
  });

  it('bounds a lossy re-encode by half its quantization step', () => {
    const corrupted = withLossyRequantization(clean, 8);

    for (let x = 0; x < clean.width; x += 1) {
      expect(Math.abs(getPixel(corrupted, x, 9)[0] - getPixel(clean, x, 9)[0])).toBeLessThanOrEqual(4);
    }
  });

  it('changes the artifact digest for every corruption', () => {
    const cleanDigest = imageSha256(clean);

    for (const corrupted of [
      withLocalizedRedraw(clean, [2, 2, 3, 3]),
      withGlobalTint(clean, 6),
      withDiffuseLowLevelEdit(clean, 2),
      withLossyRequantization(clean, 8),
    ]) {
      expect(imageSha256(corrupted)).not.toBe(cleanDigest);
    }
  });
});
