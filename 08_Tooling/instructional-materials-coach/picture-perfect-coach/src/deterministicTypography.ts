import type { RgbaColor } from './captureEvidence';
import type { CompositingColourSpace, OutputPixelRect } from './framePlan';

export const TYPOGRAPHY_BLOCKER_REASONS = {
  missingText: 'typography-text-missing',
  missingFontIdentity: 'typography-font-identity-missing',
  unsupportedDecorativeMode: 'typography-decorative-mode-unsupported',
  invalidGeometry: 'typography-geometry-invalid',
} as const;

export type TypographyBlockerReason =
  (typeof TYPOGRAPHY_BLOCKER_REASONS)[keyof typeof TYPOGRAPHY_BLOCKER_REASONS];

export type ExactStraightTextPlan = Readonly<{
  text: string;
  font_identity: string;
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

export function admitExactStraightTextPlan(
  plan: ExactStraightTextPlan,
): TypographyAdmissionResult {
  const reasons: TypographyBlockerReason[] = [];

  if (!plan.text) reasons.push(TYPOGRAPHY_BLOCKER_REASONS.missingText);
  if (!plan.font_identity.trim()) {
    reasons.push(TYPOGRAPHY_BLOCKER_REASONS.missingFontIdentity);
  }

  const [x, y, width, height] = plan.text_box.rect;
  if (
    plan.text_box.space !== 'output-pixel' ||
    !Number.isFinite(x) ||
    !Number.isFinite(y) ||
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    width <= 0 ||
    height <= 0
  ) {
    reasons.push(TYPOGRAPHY_BLOCKER_REASONS.invalidGeometry);
  }

  if (reasons.length > 0) {
    return Object.freeze({ ok: false, reasons: Object.freeze(reasons) });
  }

  return Object.freeze({ ok: true, plan: Object.freeze({ ...plan }) });
}

export type ExistingTypographyPreservation = Readonly<{
  source_derived: true;
  reconstruction_allowed: false;
}>;

export const EXISTING_TYPOGRAPHY_PRESERVATION: ExistingTypographyPreservation =
  Object.freeze({
    source_derived: true,
    reconstruction_allowed: false,
  });

export function rejectDecorativeExactTypography(): TypographyAdmissionResult {
  return Object.freeze({
    ok: false,
    reasons: Object.freeze([
      TYPOGRAPHY_BLOCKER_REASONS.unsupportedDecorativeMode,
    ]),
  });
}

import {
  createImage,
  imageSha256,
  setPixel,
  type RgbaImage,
} from './exactCompositePrimitives';

export const BUILTIN_TEST_FONT_IDENTITY = 'ppux-font:mono-5x7-v1' as const;

const GLYPHS: Readonly<Record<string, readonly string[]>> = Object.freeze({
  ' ': ['00000','00000','00000','00000','00000','00000','00000'],
  A: ['01110','10001','10001','11111','10001','10001','10001'],
  D: ['11110','10001','10001','10001','10001','10001','11110'],
  E: ['11111','10000','10000','11110','10000','10000','11111'],
  F: ['11111','10000','10000','11110','10000','10000','10000'],
  K: ['10001','10010','10100','11000','10100','10010','10001'],
  M: ['10001','11011','10101','10101','10001','10001','10001'],
  O: ['01110','10001','10001','10001','10001','10001','01110'],
  R: ['11110','10001','10001','11110','10100','10010','10001'],
  T: ['11111','00100','00100','00100','00100','00100','00100'],
  U: ['10001','10001','10001','10001','10001','10001','01110'],
});

export type DeterministicTextAsset = Readonly<{
  image: RgbaImage;
  fingerprint: string;
  font_identity: typeof BUILTIN_TEST_FONT_IDENTITY;
}>;

export type DeterministicTextRenderResult =
  | Readonly<{ ok: true; asset: DeterministicTextAsset }>
  | Readonly<{ ok: false; reasons: readonly TypographyBlockerReason[] }>;

export function renderExactStraightText(
  plan: ExactStraightTextPlan,
): DeterministicTextRenderResult {
  const admitted = admitExactStraightTextPlan(plan);
  if (!admitted.ok) return admitted;

  if (plan.font_identity !== BUILTIN_TEST_FONT_IDENTITY) {
    return Object.freeze({
      ok: false,
      reasons: Object.freeze([
        TYPOGRAPHY_BLOCKER_REASONS.missingFontIdentity,
      ]),
    });
  }

  const text = plan.text.toUpperCase();
  const glyphScale = Math.max(1, Math.floor(plan.font_size_px / 7));
  const glyphWidth = 5 * glyphScale;
  const glyphHeight = 7 * glyphScale;
  const spacing = Math.max(
    1,
    Math.round(glyphScale + plan.letter_spacing_px),
  );

  for (const character of text) {
    if (!GLYPHS[character]) {
      return Object.freeze({
        ok: false,
        reasons: Object.freeze([
          TYPOGRAPHY_BLOCKER_REASONS.unsupportedDecorativeMode,
        ]),
      });
    }
  }

  const width =
    text.length === 0
      ? 1
      : text.length * glyphWidth + (text.length - 1) * spacing;
  const height = Math.max(glyphHeight, Math.round(plan.line_height_px));

  const image = createImage(width, height, [0, 0, 0, 0]);

  let cursorX = 0;
  for (const character of text) {
    const glyph = GLYPHS[character]!;
    for (let row = 0; row < 7; row += 1) {
      for (let column = 0; column < 5; column += 1) {
        if (glyph[row]![column] !== '1') continue;

        for (let dy = 0; dy < glyphScale; dy += 1) {
          for (let dx = 0; dx < glyphScale; dx += 1) {
            setPixel(
              image,
              cursorX + column * glyphScale + dx,
              row * glyphScale + dy,
              plan.foreground_rgba,
            );
          }
        }
      }
    }
    cursorX += glyphWidth + spacing;
  }

  return Object.freeze({
    ok: true,
    asset: Object.freeze({
      image,
      fingerprint: `sha256:${imageSha256(image)}`,
      font_identity: BUILTIN_TEST_FONT_IDENTITY,
    }),
  });
}
