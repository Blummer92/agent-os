import { describe, expect, it } from 'vitest';
import {
  BUILTIN_TEST_FONT_ASSET,
  BUILTIN_TEST_FONT_FINGERPRINT,
  BUILTIN_TEST_FONT_IDENTITY,
  EXISTING_TYPOGRAPHY_PRESERVATION,
  TYPOGRAPHY_BLOCKER_REASONS,
  admitExactStraightTextPlan,
  admitTypographyPlacement,
  rejectDecorativeExactTypography,
  renderExactStraightText,
  type ApprovedGlyphFontAsset,
  type ExactStraightTextPlan,
} from './deterministicTypography';

const validPlan: ExactStraightTextPlan = {
  text: 'MUMFORD MARKET',
  font_identity: BUILTIN_TEST_FONT_IDENTITY,
  font_asset_fingerprint: BUILTIN_TEST_FONT_FINGERPRINT,
  font_size_px: 7,
  font_weight: 700,
  font_style: 'normal',
  line_height_px: 14,
  letter_spacing_px: 0,
  alignment: 'center',
  text_box: { space: 'output-pixel', rect: [8, 8, 140, 20] },
  foreground_rgba: [255, 255, 255, 1],
  compositing_colour_space: 'srgb',
  mode: 'straight',
};

function expectPreservedTypography(): void {
  expect(EXISTING_TYPOGRAPHY_PRESERVATION).toEqual({
    source_derived: true,
    reconstruction_allowed: false,
  });
}

describe('source typography authority', () => {
  it.each([
    'plain anchored text',
    'curved anchored text',
    'textured/image-filled anchored typography',
    'tiny anchored script',
    'anchored blackletter/decorative text',
    'intentionally awkward anchored overlaps',
    'Tutorial 1 source-native Adobe UI text',
    'Candy Branding anchored text',
  ])('keeps %s source-derived', () => expectPreservedTypography());

  it('does not put provider/model identity in the canonical text plan', () => {
    expect(Object.keys(validPlan)).not.toContain('provider');
    expect(Object.keys(validPlan)).not.toContain('model');
  });
});

describe('deterministic typography admission', () => {
  it('admits exact straight text with explicit approved font identity/fingerprint', () => {
    expect(admitExactStraightTextPlan(validPlan).ok).toBe(true);
  });

  it('fails closed when font identity is missing', () => {
    const result = admitExactStraightTextPlan({ ...validPlan, font_identity: ' ' });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reasons).toContain(TYPOGRAPHY_BLOCKER_REASONS.missingFontIdentity);
  });

  it('fails closed when font asset fingerprint is missing', () => {
    const result = admitExactStraightTextPlan({ ...validPlan, font_asset_fingerprint: '' });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reasons).toContain(TYPOGRAPHY_BLOCKER_REASONS.missingFontAsset);
  });

  it('fails closed when geometry is invalid', () => {
    const result = admitExactStraightTextPlan({
      ...validPlan,
      text_box: { space: 'output-pixel', rect: [8, 8, 0, 20] },
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reasons).toContain(TYPOGRAPHY_BLOCKER_REASONS.invalidGeometry);
  });

  it('fails closed for unsupported decorative exact typography', () => {
    const result = rejectDecorativeExactTypography();
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reasons).toEqual([TYPOGRAPHY_BLOCKER_REASONS.unsupportedDecorativeMode]);
  });
});

describe('approved font-asset adapter and deterministic rasterization', () => {
  it('renders repeated plans byte/pixel identically', () => {
    const first = renderExactStraightText(validPlan);
    const second = renderExactStraightText(validPlan);
    expect(first.ok).toBe(true);
    expect(second.ok).toBe(true);
    if (first.ok && second.ok) {
      expect(first.asset.fingerprint).toBe(second.asset.fingerprint);
      expect([...first.asset.image.data]).toEqual([...second.asset.image.data]);
    }
  });

  it('accepts an explicitly supplied approved font asset rather than discovering a system font', () => {
    const approved: ApprovedGlyphFontAsset = {
      ...BUILTIN_TEST_FONT_ASSET,
      font_identity: 'approved-font:classroom-label-v1',
      font_fingerprint: 'sha256:classroom-label-v1',
    };
    const result = renderExactStraightText(
      {
        ...validPlan,
        font_identity: approved.font_identity,
        font_asset_fingerprint: approved.font_fingerprint,
      },
      new Map([[approved.font_identity, approved]]),
    );
    expect(result.ok).toBe(true);
  });

  it('fails closed when the required approved font asset is unavailable', () => {
    const result = renderExactStraightText({
      ...validPlan,
      font_identity: 'approved-font:abril-fatface',
      font_asset_fingerprint: 'sha256:abril-fatface-approved',
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reasons).toContain(TYPOGRAPHY_BLOCKER_REASONS.missingFontAsset);
  });

  it('fails closed when approved font fingerprint does not match', () => {
    const result = renderExactStraightText({
      ...validPlan,
      font_asset_fingerprint: 'sha256:wrong',
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reasons).toContain(TYPOGRAPHY_BLOCKER_REASONS.fontFingerprintMismatch);
  });

  it('fails closed for unsupported weight instead of ignoring it', () => {
    const result = renderExactStraightText({ ...validPlan, font_weight: 400 });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reasons).toContain(TYPOGRAPHY_BLOCKER_REASONS.unsupportedFontWeight);
  });

  it('fails closed for unsupported style instead of ignoring it', () => {
    const result = renderExactStraightText({ ...validPlan, font_style: 'italic' });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reasons).toContain(TYPOGRAPHY_BLOCKER_REASONS.unsupportedFontStyle);
  });

  it('fails closed for unsupported compositing colour space instead of ignoring it', () => {
    const invalidExternalPlan = {
      ...validPlan,
      compositing_colour_space: 'linear-srgb',
    } as unknown as ExactStraightTextPlan;
    const result = renderExactStraightText(invalidExternalPlan);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reasons).toContain(TYPOGRAPHY_BLOCKER_REASONS.unsupportedColourSpace);
  });

  it('fails closed for unsupported glyphs rather than substituting them', () => {
    const result = renderExactStraightText({ ...validPlan, text: 'MUMFORD ♥' });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reasons).toContain(TYPOGRAPHY_BLOCKER_REASONS.unsupportedGlyph);
  });

  it('fails closed when exact text does not fit the declared box', () => {
    const result = renderExactStraightText({
      ...validPlan,
      text_box: { space: 'output-pixel', rect: [8, 8, 20, 20] },
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reasons).toContain(TYPOGRAPHY_BLOCKER_REASONS.textOverflow);
  });

  it('alignment is a pixel-affecting plan control', () => {
    const left = renderExactStraightText({ ...validPlan, alignment: 'left' });
    const right = renderExactStraightText({ ...validPlan, alignment: 'right' });
    expect(left.ok && right.ok).toBe(true);
    if (left.ok && right.ok) expect(left.asset.fingerprint).not.toBe(right.asset.fingerprint);
  });

  it('letter spacing is a pixel-affecting plan control', () => {
    const normal = renderExactStraightText(validPlan);
    const spaced = renderExactStraightText({ ...validPlan, letter_spacing_px: 2 });
    expect(normal.ok && spaced.ok).toBe(true);
    if (normal.ok && spaced.ok) expect(normal.asset.fingerprint).not.toBe(spaced.asset.fingerprint);
  });

  it('text-box geometry is carried into exact placement', () => {
    const result = renderExactStraightText(validPlan);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.asset.destination).toEqual(validPlan.text_box);
  });
});

describe('regional text/anchor authority', () => {
  const anchor = {
    region_id: 'source-ui',
    rect: { space: 'output-pixel' as const, rect: [0, 40, 160, 40] as const },
  };

  it('admits deterministic text outside source-native UI anchors', () => {
    expect(admitTypographyPlacement(validPlan.text_box, [anchor]).ok).toBe(true);
  });

  it('blocks deterministic text that overlaps a fill_allowed:false/source anchor', () => {
    const result = admitTypographyPlacement(
      { space: 'output-pixel', rect: [8, 35, 140, 20] },
      [anchor],
    );
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reasons).toContain(TYPOGRAPHY_BLOCKER_REASONS.anchorOverlap);
  });

  it('keeps Candy placeholder replacement regional: authorized fill text cannot alter neighboring anchors', () => {
    const fillText = { space: 'output-pixel' as const, rect: [8, 8, 140, 20] as const };
    expect(admitTypographyPlacement(fillText, [anchor]).ok).toBe(true);
    expect(admitTypographyPlacement({ ...fillText, rect: [8, 35, 140, 20] }, [anchor]).ok).toBe(false);
  });

  it('#1497 artwork/text spill into an exact anchor is rejected by the same regional boundary', () => {
    const onePixelSpill = { space: 'output-pixel' as const, rect: [0, 39, 10, 2] as const };
    expect(admitTypographyPlacement(onePixelSpill, [anchor]).ok).toBe(false);
  });
});

describe('#1484 provenance integration', () => {
  it('feeds deterministic exact text through ExactAssetFill/Gate A without changing neighboring source pixels', async () => {
    const { createImage, placeAsset } = await import('./exactCompositePrimitives');
    const { validatePixelFidelity } = await import('./provenanceValidator');
    const rendered = renderExactStraightText(validPlan);
    expect(rendered.ok).toBe(true);
    if (!rendered.ok) return;

    const source = createImage(160, 80, [30, 30, 30, 1]);
    const destination = rendered.asset.destination;
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
      source_rect: { space: 'source-pixel' as const, rect: [0, 0, 160, 80] as const },
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
        spotlight: { padding_px: 12, falloff_px: 0, falloff_function: 'none' as const },
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
        inset: { magnification: 2, border_width_px: 3, border_rgba: [255, 255, 255, 1] as const },
      },
      asset_fills: [{
        fill_id: 'deterministic-text',
        asset_id: 'deterministic-text:MUMFORD-MARKET',
        asset_fingerprint: rendered.asset.fingerprint,
        destination,
      }],
      overlays: [],
      anchored_rects: [{
        region_id: 'source-ui',
        rect: { space: 'output-pixel' as const, rect: [0, 40, 160, 40] as const },
      }],
      must_show_region_ids: ['source-ui'],
      annotation_intent: { target_region_id: 'title', label: null, preferred_side: null },
      execution_authorized: false as const,
    };

    expect(admitTypographyPlacement(destination, plan.anchored_rects).ok).toBe(true);
    const output = createImage(160, 80, [30, 30, 30, 1]);
    placeAsset(output, rendered.asset.image, destination.rect);
    const result = validatePixelFidelity({
      plan,
      source,
      output,
      assets: new Map([[
        'deterministic-text:MUMFORD-MARKET',
        { image: rendered.asset.image, fingerprint: rendered.asset.fingerprint },
      ]]),
    });
    expect(result.passed).toBe(true);
    expect(result.blocker_reasons).toEqual([]);
  });
});
