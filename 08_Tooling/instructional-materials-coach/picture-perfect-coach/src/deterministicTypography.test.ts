import { describe, expect, it } from 'vitest';
import {
  EXISTING_TYPOGRAPHY_PRESERVATION,
  TYPOGRAPHY_BLOCKER_REASONS,
  admitExactStraightTextPlan,
  rejectDecorativeExactTypography,
  type ExactStraightTextPlan,
} from './deterministicTypography';

const validPlan: ExactStraightTextPlan = {
  text: 'MUMFORD MARKET',
  font_identity: 'approved-font:abril-fatface',
  font_size_px: 48,
  font_weight: 700,
  font_style: 'normal',
  line_height_px: 52,
  letter_spacing_px: 0,
  alignment: 'center',
  text_box: {
    space: 'output-pixel',
    rect: [100, 120, 420, 120],
  },
  foreground_rgba: [255, 255, 255, 1],
  compositing_colour_space: 'srgb',
  mode: 'straight',
};

describe('deterministic typography admission', () => {
  it('admits exact straight text with explicit plan values', () => {
    const result = admitExactStraightTextPlan(validPlan);
    expect(result.ok).toBe(true);
  });

  it('fails closed when font identity is missing', () => {
    const result = admitExactStraightTextPlan({
      ...validPlan,
      font_identity: '   ',
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reasons).toContain(
        TYPOGRAPHY_BLOCKER_REASONS.missingFontIdentity,
      );
    }
  });

  it('fails closed when geometry is invalid', () => {
    const result = admitExactStraightTextPlan({
      ...validPlan,
      text_box: {
        space: 'output-pixel',
        rect: [100, 120, 0, 120],
      },
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reasons).toContain(
        TYPOGRAPHY_BLOCKER_REASONS.invalidGeometry,
      );
    }
  });

  it('fails closed for unsupported decorative exact typography', () => {
    const result = rejectDecorativeExactTypography();
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reasons).toEqual([
        TYPOGRAPHY_BLOCKER_REASONS.unsupportedDecorativeMode,
      ]);
    }
  });

  it('declares existing typography source-derived and non-reconstructable', () => {
    expect(EXISTING_TYPOGRAPHY_PRESERVATION).toEqual({
      source_derived: true,
      reconstruction_allowed: false,
    });
  });

  it('keeps provider identity out of the canonical plan shape', () => {
    expect(Object.keys(validPlan)).not.toContain('provider');
    expect(Object.keys(validPlan)).not.toContain('model');
  });
});

describe('deterministic typography rasterization', () => {
  it('renders the same exact text to byte-identical pixels repeatedly', async () => {
    const { BUILTIN_TEST_FONT_IDENTITY, renderExactStraightText } =
      await import('./deterministicTypography');

    const plan = {
      ...validPlan,
      font_identity: BUILTIN_TEST_FONT_IDENTITY,
    };

    const first = renderExactStraightText(plan);
    const second = renderExactStraightText(plan);

    expect(first.ok).toBe(true);
    expect(second.ok).toBe(true);

    if (first.ok && second.ok) {
      expect(first.asset.fingerprint).toBe(second.asset.fingerprint);
      expect([...first.asset.image.data]).toEqual([...second.asset.image.data]);
    }
  });

  it('fails closed instead of using an unavailable system font', async () => {
    const { renderExactStraightText } =
      await import('./deterministicTypography');

    const result = renderExactStraightText({
      ...validPlan,
      font_identity: 'system-font:Arial',
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reasons).toContain(
        TYPOGRAPHY_BLOCKER_REASONS.missingFontIdentity,
      );
    }
  });

  it('fails closed for unsupported glyphs', async () => {
    const { BUILTIN_TEST_FONT_IDENTITY, renderExactStraightText } =
      await import('./deterministicTypography');

    const result = renderExactStraightText({
      ...validPlan,
      text: 'MUMFORD MARKET ♥',
      font_identity: BUILTIN_TEST_FONT_IDENTITY,
    });

    expect(result.ok).toBe(false);
  });
});

describe('deterministic typography provenance integration', () => {
  it('feeds deterministic text through ExactAssetFill and passes Gate A', async () => {
    const {
      BUILTIN_TEST_FONT_IDENTITY,
      renderExactStraightText,
    } = await import('./deterministicTypography');
    const { createImage, placeAsset } =
      await import('./exactCompositePrimitives');
    const { validatePixelFidelity } =
      await import('./provenanceValidator');

    const rendered = renderExactStraightText({
      ...validPlan,
      text: 'MUMFORD MARKET',
      font_identity: BUILTIN_TEST_FONT_IDENTITY,
      font_size_px: 14,
      line_height_px: 14,
      text_box: {
        space: 'output-pixel',
        rect: [8, 8, 120, 14],
      },
    });

    expect(rendered.ok).toBe(true);
    if (!rendered.ok) return;

    const source = createImage(160, 80, [30, 30, 30, 1]);

    const destination = {
      space: 'output-pixel' as const,
      rect: [
        8,
        8,
        rendered.asset.image.width,
        rendered.asset.image.height,
      ] as const,
    };

    const plan = {
      plan_version: 'picture-perfect-exact-composite-plan-v1' as const,
      schema_version: 'tutorial-frame-plan-v1',
      rect_convention: 'xywh' as const,
      base_reference: {
        reference_id: 'typography-source',
        stable_ref: 'fixture://typography-source',
        content_fingerprint: 'sha256:source',
      },
      resolved_target_region_id: 'title',
      source_rect: {
        space: 'source-pixel' as const,
        rect: [0, 0, 160, 80] as const,
      },
      output_aspect: { width: 2, height: 1 },
      output_width_px: 160,
      output_height_px: 80,
      render_mode: 'crop-only' as const,
      scale_x: 1,
      scale_y: 1,
      render_spec: {
        compositing_colour_space: 'srgb' as const,
        dim_rgba: [0, 0, 0, 0] as const,
        resampler: 'none' as const,
        overlay_bleed_px: 2,
        annotation_clearance_px: 16,
        context_margin_fraction: 0.08,
        spotlight: {
          padding_px: 12,
          falloff_px: 0,
          falloff_function: 'none' as const,
        },
        badge: {
          diameter_px: 44,
          border_width_px: 3,
          fill_rgba: [255, 255, 255, 1] as const,
          border_rgba: [17, 17, 17, 1] as const,
          text_rgba: [17, 17, 17, 1] as const,
          font_family: 'test',
          font_size_px: 22,
          font_weight: 700,
        },
        arrow: {
          shaft_width_px: 6,
          head_length_px: 18,
          head_width_px: 16,
          rgba: [255, 255, 255, 1] as const,
        },
        label: {
          font_family: 'test',
          font_size_px: 18,
          font_weight: 600,
          line_height_px: 24,
          padding_x_px: 12,
          padding_y_px: 8,
          corner_radius_px: 8,
          max_width_px: 320,
          background_rgba: [17, 17, 17, 0.92] as const,
          text_rgba: [255, 255, 255, 1] as const,
        },
        inset: {
          magnification: 2,
          border_width_px: 3,
          border_rgba: [255, 255, 255, 1] as const,
        },
      },
      asset_fills: [
        {
          fill_id: 'deterministic-text',
          asset_id: 'deterministic-text:MUMFORD-MARKET',
          asset_fingerprint: rendered.asset.fingerprint,
          destination,
        },
      ],
      overlays: [],
      anchored_rects: [
        {
          region_id: 'source-ui',
          rect: {
            space: 'output-pixel' as const,
            rect: [0, 40, 160, 40] as const,
          },
        },
      ],
      must_show_region_ids: ['source-ui'],
      annotation_intent: {
        target_region_id: 'title',
        label: null,
        preferred_side: null,
      },
      execution_authorized: false as const,
    };

    const output = createImage(160, 80, [30, 30, 30, 1]);
    placeAsset(output, rendered.asset.image, destination.rect);

    const result = validatePixelFidelity({
      plan,
      source,
      output,
      assets: new Map([
        [
          'deterministic-text:MUMFORD-MARKET',
          {
            image: rendered.asset.image,
            fingerprint: rendered.asset.fingerprint,
          },
        ],
      ]),
    });

    expect(result.passed).toBe(true);
    expect(result.blocker_reasons).toEqual([]);
  });
});
