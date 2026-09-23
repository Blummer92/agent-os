import type { RgbaColor } from './captureEvidence';
import type {
  AnchoredRegionRect,
  CompositingColourSpace,
  OutputPixelRect,
} from './framePlan';
import {
  createImage,
  imageSha256,
  setPixel,
  type RgbaImage,
} from './exactCompositePrimitives';

export const TYPOGRAPHY_BLOCKER_REASONS = {
  missingText: 'typography-text-missing',
  missingFontIdentity: 'typography-font-identity-missing',
  missingFontAsset: 'typography-font-asset-missing',
  fontFingerprintMismatch: 'typography-font-fingerprint-mismatch',
  unsupportedDecorativeMode: 'typography-decorative-mode-unsupported',
  unsupportedGlyph: 'typography-glyph-unsupported',
  unsupportedFontWeight: 'typography-font-weight-unsupported',
  unsupportedFontStyle: 'typography-font-style-unsupported',
  unsupportedColourSpace: 'typography-colour-space-unsupported',
  invalidGeometry: 'typography-geometry-invalid',
  textOverflow: 'typography-text-overflow',
  anchorOverlap: 'typography-anchor-overlap',
} as const;

export type TypographyBlockerReason =
  (typeof TYPOGRAPHY_BLOCKER_REASONS)[keyof typeof TYPOGRAPHY_BLOCKER_REASONS];

export type ExactStraightTextPlan = Readonly<{
  text: string;
  font_identity: string;
  font_asset_fingerprint: string;
  font_size_px: number;
  font_weight: number;
  font_style: 'normal' | 'italic';
  line_height_px: number;
  letter_spacing_px: number;
  alignment: 'left' | 'center' | 'right';
  text_box: OutputPixelRect;
  foreground_rgba: RgbaColor;
  compositing_colour_space: CompositingColourSpace;
  mode: 'straight';
}>;

export type TypographyAdmissionResult =
  | Readonly<{ ok: true; plan: ExactStraightTextPlan }>
  | Readonly<{ ok: false; reasons: readonly TypographyBlockerReason[] }>;

function positiveInteger(value: number): boolean {
  return Number.isInteger(value) && value > 0;
}

export function admitExactStraightTextPlan(
  plan: ExactStraightTextPlan,
): TypographyAdmissionResult {
  const reasons = new Set<TypographyBlockerReason>();

  if (!plan.text) reasons.add(TYPOGRAPHY_BLOCKER_REASONS.missingText);
  if (!plan.font_identity.trim()) reasons.add(TYPOGRAPHY_BLOCKER_REASONS.missingFontIdentity);
  if (!plan.font_asset_fingerprint.trim()) reasons.add(TYPOGRAPHY_BLOCKER_REASONS.missingFontAsset);

  const [x, y, width, height] = plan.text_box.rect;
  if (
    plan.text_box.space !== 'output-pixel' ||
    !Number.isInteger(x) ||
    !Number.isInteger(y) ||
    !positiveInteger(width) ||
    !positiveInteger(height) ||
    !positiveInteger(plan.font_size_px) ||
    !positiveInteger(plan.line_height_px) ||
    !Number.isFinite(plan.letter_spacing_px)
  ) {
    reasons.add(TYPOGRAPHY_BLOCKER_REASONS.invalidGeometry);
  }

  if (reasons.size > 0) {
    return Object.freeze({ ok: false, reasons: Object.freeze([...reasons]) });
  }

  return Object.freeze({ ok: true, plan: Object.freeze({ ...plan }) });
}

export type ExistingTypographyPreservation = Readonly<{
  source_derived: true;
  reconstruction_allowed: false;
}>;

export const EXISTING_TYPOGRAPHY_PRESERVATION: ExistingTypographyPreservation =
  Object.freeze({ source_derived: true, reconstruction_allowed: false });

export function rejectDecorativeExactTypography(): TypographyAdmissionResult {
  return Object.freeze({
    ok: false,
    reasons: Object.freeze([TYPOGRAPHY_BLOCKER_REASONS.unsupportedDecorativeMode]),
  });
}

export type ApprovedGlyphFontAsset = Readonly<{
  font_identity: string;
  font_fingerprint: string;
  glyph_width: number;
  glyph_height: number;
  supported_weights: readonly number[];
  supported_styles: readonly ('normal' | 'italic')[];
  glyphs: Readonly<Record<string, readonly string[]>>;
}>;

export const BUILTIN_TEST_FONT_IDENTITY = 'ppux-font:mono-5x7-v1' as const;
export const BUILTIN_TEST_FONT_FINGERPRINT = 'sha256:ppux-font-mono-5x7-v1' as const;

const BUILTIN_GLYPHS: Readonly<Record<string, readonly string[]>> = Object.freeze({
  ' ': ['00000', '00000', '00000', '00000', '00000', '00000', '00000'],
  A: ['01110', '10001', '10001', '11111', '10001', '10001', '10001'],
  D: ['11110', '10001', '10001', '10001', '10001', '10001', '11110'],
  E: ['11111', '10000', '10000', '11110', '10000', '10000', '11111'],
  F: ['11111', '10000', '10000', '11110', '10000', '10000', '10000'],
  K: ['10001', '10010', '10100', '11000', '10100', '10010', '10001'],
  M: ['10001', '11011', '10101', '10101', '10001', '10001', '10001'],
  O: ['01110', '10001', '10001', '10001', '10001', '10001', '01110'],
  R: ['11110', '10001', '10001', '11110', '10100', '10010', '10001'],
  T: ['11111', '00100', '00100', '00100', '00100', '00100', '00100'],
  U: ['10001', '10001', '10001', '10001', '10001', '10001', '01110'],
});

export const BUILTIN_TEST_FONT_ASSET: ApprovedGlyphFontAsset = Object.freeze({
  font_identity: BUILTIN_TEST_FONT_IDENTITY,
  font_fingerprint: BUILTIN_TEST_FONT_FINGERPRINT,
  glyph_width: 5,
  glyph_height: 7,
  supported_weights: Object.freeze([700]),
  supported_styles: Object.freeze(['normal'] as const),
  glyphs: BUILTIN_GLYPHS,
});

export type ApprovedFontRegistry = ReadonlyMap<string, ApprovedGlyphFontAsset>;

function defaultFontRegistry(): ApprovedFontRegistry {
  return new Map([[BUILTIN_TEST_FONT_IDENTITY, BUILTIN_TEST_FONT_ASSET]]);
}

export type DeterministicTextAsset = Readonly<{
  image: RgbaImage;
  fingerprint: string;
  font_identity: string;
  font_fingerprint: string;
  destination: OutputPixelRect;
}>;

export type DeterministicTextRenderResult =
  | Readonly<{ ok: true; asset: DeterministicTextAsset }>
  | Readonly<{ ok: false; reasons: readonly TypographyBlockerReason[] }>;

function blocked(...reasons: TypographyBlockerReason[]): DeterministicTextRenderResult {
  return Object.freeze({ ok: false, reasons: Object.freeze(reasons) });
}

function textPixelWidth(
  text: string,
  asset: ApprovedGlyphFontAsset,
  scale: number,
  spacing: number,
): number {
  if (text.length === 0) return 0;
  return text.length * asset.glyph_width * scale + (text.length - 1) * spacing;
}

function alignedStartX(alignment: ExactStraightTextPlan['alignment'], boxWidth: number, textWidth: number): number {
  if (alignment === 'center') return Math.floor((boxWidth - textWidth) / 2);
  if (alignment === 'right') return boxWidth - textWidth;
  return 0;
}

export function renderExactStraightText(
  plan: ExactStraightTextPlan,
  fonts: ApprovedFontRegistry = defaultFontRegistry(),
): DeterministicTextRenderResult {
  const admitted = admitExactStraightTextPlan(plan);
  if (!admitted.ok) return admitted;

  const font = fonts.get(plan.font_identity);
  if (!font) return blocked(TYPOGRAPHY_BLOCKER_REASONS.missingFontAsset);
  if (font.font_fingerprint !== plan.font_asset_fingerprint) {
    return blocked(TYPOGRAPHY_BLOCKER_REASONS.fontFingerprintMismatch);
  }
  if (!font.supported_weights.includes(plan.font_weight)) {
    return blocked(TYPOGRAPHY_BLOCKER_REASONS.unsupportedFontWeight);
  }
  if (!font.supported_styles.includes(plan.font_style)) {
    return blocked(TYPOGRAPHY_BLOCKER_REASONS.unsupportedFontStyle);
  }
  if (plan.compositing_colour_space !== 'srgb') {
    return blocked(TYPOGRAPHY_BLOCKER_REASONS.unsupportedColourSpace);
  }

  for (const character of plan.text) {
    if (!font.glyphs[character]) return blocked(TYPOGRAPHY_BLOCKER_REASONS.unsupportedGlyph);
  }

  const scale = Math.max(1, Math.floor(plan.font_size_px / font.glyph_height));
  const glyphHeight = font.glyph_height * scale;
  const spacing = Math.max(0, Math.round(scale + plan.letter_spacing_px));
  const width = textPixelWidth(plan.text, font, scale, spacing);
  const [, , boxWidth, boxHeight] = plan.text_box.rect;
  if (width > boxWidth || glyphHeight > plan.line_height_px || plan.line_height_px > boxHeight) {
    return blocked(TYPOGRAPHY_BLOCKER_REASONS.textOverflow);
  }

  const image = createImage(boxWidth, boxHeight, [0, 0, 0, 0]);
  let cursorX = alignedStartX(plan.alignment, boxWidth, width);
  const lineTop = Math.floor((plan.line_height_px - glyphHeight) / 2);

  for (const character of plan.text) {
    const glyph = font.glyphs[character]!;
    for (let row = 0; row < font.glyph_height; row += 1) {
      for (let column = 0; column < font.glyph_width; column += 1) {
        if (glyph[row]?.[column] !== '1') continue;
        for (let dy = 0; dy < scale; dy += 1) {
          for (let dx = 0; dx < scale; dx += 1) {
            setPixel(
              image,
              cursorX + column * scale + dx,
              lineTop + row * scale + dy,
              plan.foreground_rgba,
            );
          }
        }
      }
    }
    cursorX += font.glyph_width * scale + spacing;
  }

  return Object.freeze({
    ok: true,
    asset: Object.freeze({
      image,
      fingerprint: `sha256:${imageSha256(image)}`,
      font_identity: font.font_identity,
      font_fingerprint: font.font_fingerprint,
      destination: plan.text_box,
    }),
  });
}

function rectsOverlap(left: OutputPixelRect, right: OutputPixelRect): boolean {
  const [lx, ly, lw, lh] = left.rect;
  const [rx, ry, rw, rh] = right.rect;
  return lx < rx + rw && lx + lw > rx && ly < ry + rh && ly + lh > ry;
}

export type TypographyPlacementResult =
  | Readonly<{ ok: true }>
  | Readonly<{ ok: false; reasons: readonly TypographyBlockerReason[] }>;

export function admitTypographyPlacement(
  destination: OutputPixelRect,
  anchoredRects: readonly AnchoredRegionRect[],
): TypographyPlacementResult {
  if (anchoredRects.some((anchor) => rectsOverlap(destination, anchor.rect))) {
    return Object.freeze({
      ok: false,
      reasons: Object.freeze([TYPOGRAPHY_BLOCKER_REASONS.anchorOverlap]),
    });
  }
  return Object.freeze({ ok: true });
}
