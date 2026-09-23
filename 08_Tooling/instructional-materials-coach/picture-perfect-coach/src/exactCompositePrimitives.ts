import type { RgbaColor } from './captureEvidence';
import type { CompositingColourSpace, RectXywh, ResamplerName, SpotlightFalloffFunction } from './framePlan';

/**
 * PPUX-VRL7 (#1484) deterministic raster primitives and artifact identity.
 *
 * These are the shared operations the exact-composite path is allowed to
 * perform -- crop, proportional scale, asset placement, dim, spotlight -- plus
 * the digest that binds a report to a real artifact. They are shared because
 * two callers need exactly the same arithmetic: the fixture reference renderer
 * that produces a trusted known-good pair, and the independent validator that
 * forward-constructs its expected image. Any drift between those two would show
 * up as a false pixel-fidelity result.
 *
 * Nothing here inspects content. There is no thresholding, edge finding,
 * brightness scanning, feature detection, OCR, or scoring: every operation is a
 * fixed arithmetic transform whose parameters come from a resolved plan.
 *
 * Everything is pure TypeScript with no dependency and no platform global. The
 * package has no `@types/node`, and jsdom's `Crypto` implements only
 * `getRandomValues` and `randomUUID`, so neither `node:crypto` nor
 * `crypto.subtle` is available to this code.
 */

/** Straight-alpha RGBA8, row-major, four bytes per pixel. */
export type RgbaImage = Readonly<{
  width: number;
  height: number;
  data: Uint8ClampedArray;
}>;

export function createImage(width: number, height: number, fill: RgbaColor = [0, 0, 0, 1]): RgbaImage {
  const data = new Uint8ClampedArray(width * height * 4);
  const [r, g, b, a] = fill;
  const alpha = Math.round(a * 255);
  for (let index = 0; index < data.length; index += 4) {
    data[index] = r;
    data[index + 1] = g;
    data[index + 2] = b;
    data[index + 3] = alpha;
  }
  return { width, height, data };
}

export function cloneImage(image: RgbaImage): RgbaImage {
  return { width: image.width, height: image.height, data: new Uint8ClampedArray(image.data) };
}

function offsetOf(image: RgbaImage, x: number, y: number): number {
  return (y * image.width + x) * 4;
}

export function getPixel(image: RgbaImage, x: number, y: number): RgbaColor {
  const at = offsetOf(image, x, y);
  return [image.data[at]!, image.data[at + 1]!, image.data[at + 2]!, image.data[at + 3]! / 255];
}

export function setPixel(image: RgbaImage, x: number, y: number, colour: RgbaColor): void {
  const at = offsetOf(image, x, y);
  image.data[at] = colour[0];
  image.data[at + 1] = colour[1];
  image.data[at + 2] = colour[2];
  image.data[at + 3] = Math.round(colour[3] * 255);
}

/* ---------------------------- colour space ---------------------------- */

function srgbToLinear(channel: number): number {
  const value = channel / 255;
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

function linearToSrgb(value: number): number {
  const encoded = value <= 0.0031308 ? value * 12.92 : 1.055 * value ** (1 / 2.4) - 0.055;
  return Math.round(Math.min(1, Math.max(0, encoded)) * 255);
}

/**
 * Blend `over` onto `under` at `amount` in the declared compositing space. The
 * space is a plan-controlled value, never guessed: dimming the same pixels in
 * sRGB and in linear light produces measurably different output, which is why
 * #1484 requires it to be declared and validated.
 */
export function blendChannel(
  under: number,
  over: number,
  amount: number,
  space: CompositingColourSpace,
): number {
  if (amount <= 0) return under;
  if (space === 'srgb') return Math.round(under * (1 - amount) + over * amount);
  const blended = srgbToLinear(under) * (1 - amount) + srgbToLinear(over) * amount;
  return linearToSrgb(blended);
}

/* ------------------------------ geometry ------------------------------ */

export function cropImage(image: RgbaImage, rect: RectXywh): RgbaImage {
  const [left, top, width, height] = rect;
  const cropped = createImage(width, height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      setPixel(cropped, x, y, getPixel(image, left + x, top + y));
    }
  }
  return cropped;
}

/**
 * Proportional resample. `none` is not a silent alias for nearest: a caller
 * that declares no resampling and then changes dimensions has an incoherent
 * plan, and pretending otherwise would hide it from the pixel comparison.
 */
export function scaleImage(
  image: RgbaImage,
  width: number,
  height: number,
  resampler: ResamplerName,
): RgbaImage {
  if (resampler === 'none') {
    if (width !== image.width || height !== image.height) {
      throw new RangeError('resampler "none" requires identical source and output dimensions');
    }
    return cloneImage(image);
  }

  const scaled = createImage(width, height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (resampler === 'nearest') {
        const sourceX = Math.min(image.width - 1, Math.floor(((x + 0.5) * image.width) / width));
        const sourceY = Math.min(image.height - 1, Math.floor(((y + 0.5) * image.height) / height));
        setPixel(scaled, x, y, getPixel(image, sourceX, sourceY));
        continue;
      }

      const sampleX = Math.min(image.width - 1, Math.max(0, ((x + 0.5) * image.width) / width - 0.5));
      const sampleY = Math.min(image.height - 1, Math.max(0, ((y + 0.5) * image.height) / height - 0.5));
      const leftX = Math.floor(sampleX);
      const topY = Math.floor(sampleY);
      const rightX = Math.min(image.width - 1, leftX + 1);
      const bottomY = Math.min(image.height - 1, topY + 1);
      const weightX = sampleX - leftX;
      const weightY = sampleY - topY;

      const topLeft = getPixel(image, leftX, topY);
      const topRight = getPixel(image, rightX, topY);
      const bottomLeft = getPixel(image, leftX, bottomY);
      const bottomRight = getPixel(image, rightX, bottomY);
      const channel = (index: 0 | 1 | 2): number => Math.round(
        (topLeft[index] * (1 - weightX) + topRight[index] * weightX) * (1 - weightY) +
        (bottomLeft[index] * (1 - weightX) + bottomRight[index] * weightX) * weightY,
      );
      setPixel(scaled, x, y, [channel(0), channel(1), channel(2), 1]);
    }
  }
  return scaled;
}

/** Copy an approved exact asset into place, nearest-sampled, pixels only. */
export function placeAsset(target: RgbaImage, asset: RgbaImage, destination: RectXywh): void {
  const [left, top, width, height] = destination;
  const resized = scaleImage(asset, width, height, width === asset.width && height === asset.height ? 'none' : 'nearest');
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const targetX = left + x;
      const targetY = top + y;
      if (targetX < 0 || targetY < 0 || targetX >= target.width || targetY >= target.height) continue;
      setPixel(target, targetX, targetY, getPixel(resized, x, y));
    }
  }
}

export function fillRect(target: RgbaImage, rect: RectXywh, colour: RgbaColor): void {
  const [left, top, width, height] = rect;
  for (let y = top; y < top + height; y += 1) {
    for (let x = left; x < left + width; x += 1) {
      if (x < 0 || y < 0 || x >= target.width || y >= target.height) continue;
      setPixel(target, x, y, colour);
    }
  }
}

export type SpotlightSpec = Readonly<{
  boundary: RectXywh;
  falloff_px: number;
  falloff_function: SpotlightFalloffFunction;
}>;

/** L-infinity distance outside the boundary rect; 0 for a pixel inside it. */
function distanceOutside(rect: RectXywh, x: number, y: number): number {
  const [left, top, width, height] = rect;
  const horizontal = Math.max(left - x, x - (left + width - 1), 0);
  const vertical = Math.max(top - y, y - (top + height - 1), 0);
  return Math.max(horizontal, vertical);
}

function falloffAmount(distance: number, spotlight: SpotlightSpec): number {
  if (distance <= 0) return 0;
  if (spotlight.falloff_function === 'none' || spotlight.falloff_px <= 0) return 1;
  const ratio = Math.min(1, distance / spotlight.falloff_px);
  if (spotlight.falloff_function === 'linear') return ratio;
  return ratio * ratio * (3 - 2 * ratio);
}

/**
 * Dim the frame, optionally holding a spotlight open. With no spotlight the dim
 * is uniform; with one, pixels inside the boundary keep their source values and
 * the declared falloff ramps to full dim across `falloff_px`.
 */
export function dimImage(
  image: RgbaImage,
  dim: RgbaColor,
  space: CompositingColourSpace,
  spotlight: SpotlightSpec | null = null,
): RgbaImage {
  const dimmed = cloneImage(image);
  const strength = dim[3];
  for (let y = 0; y < image.height; y += 1) {
    for (let x = 0; x < image.width; x += 1) {
      const amount = spotlight
        ? strength * falloffAmount(distanceOutside(spotlight.boundary, x, y), spotlight)
        : strength;
      if (amount <= 0) continue;
      const [r, g, b, a] = getPixel(image, x, y);
      setPixel(dimmed, x, y, [
        blendChannel(r, dim[0], amount, space),
        blendChannel(g, dim[1], amount, space),
        blendChannel(b, dim[2], amount, space),
        a,
      ]);
    }
  }
  return dimmed;
}

/* --------------------------- artifact identity --------------------------- */

export function utf8Bytes(value: string): Uint8Array {
  const bytes: number[] = [];
  for (let index = 0; index < value.length; index += 1) {
    let code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff && index + 1 < value.length) {
      const low = value.charCodeAt(index + 1);
      if (low >= 0xdc00 && low <= 0xdfff) {
        code = 0x10000 + ((code - 0xd800) << 10) + (low - 0xdc00);
        index += 1;
      }
    }
    if (code < 0x80) bytes.push(code);
    else if (code < 0x800) bytes.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
    else if (code < 0x10000) bytes.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
    else {
      bytes.push(
        0xf0 | (code >> 18),
        0x80 | ((code >> 12) & 0x3f),
        0x80 | ((code >> 6) & 0x3f),
        0x80 | (code & 0x3f),
      );
    }
  }
  return new Uint8Array(bytes);
}

/** Recursively key-sorted JSON, so a plan's digest is independent of key order. */
export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? 'null';
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, item]) => item !== undefined)
    .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0));
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(',')}}`;
}

const SHA256_K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

/** Pure-TypeScript SHA-256. No platform digest API is available to this package. */
export function sha256Hex(input: Uint8Array): string {
  const state = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  const bitLength = input.length * 8;
  const padded = new Uint8Array((((input.length + 9) >> 6) + 1) << 6);
  padded.set(input);
  padded[input.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 8, Math.floor(bitLength / 0x100000000), false);
  view.setUint32(padded.length - 4, bitLength >>> 0, false);

  const schedule = new Uint32Array(64);
  for (let block = 0; block < padded.length; block += 64) {
    for (let index = 0; index < 16; index += 1) schedule[index] = view.getUint32(block + index * 4, false);
    for (let index = 16; index < 64; index += 1) {
      const a = schedule[index - 15]!;
      const b = schedule[index - 2]!;
      const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
      const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
      schedule[index] = (schedule[index - 16]! + s0 + schedule[index - 7]! + s1) >>> 0;
    }

    let [a, b, c, d, e, f, g, h] = state;
    for (let index = 0; index < 64; index += 1) {
      const s1 = ((e! >>> 6) | (e! << 26)) ^ ((e! >>> 11) | (e! << 21)) ^ ((e! >>> 25) | (e! << 7));
      const choose = (e! & f!) ^ (~e! & g!);
      const temp1 = (h! + s1 + choose + SHA256_K[index]! + schedule[index]!) >>> 0;
      const s0 = ((a! >>> 2) | (a! << 30)) ^ ((a! >>> 13) | (a! << 19)) ^ ((a! >>> 22) | (a! << 10));
      const majority = (a! & b!) ^ (a! & c!) ^ (b! & c!);
      const temp2 = (s0 + majority) >>> 0;
      h = g; g = f; f = e; e = (d! + temp1) >>> 0;
      d = c; c = b; b = a; a = (temp1 + temp2) >>> 0;
    }
    state[0] = (state[0]! + a!) >>> 0;
    state[1] = (state[1]! + b!) >>> 0;
    state[2] = (state[2]! + c!) >>> 0;
    state[3] = (state[3]! + d!) >>> 0;
    state[4] = (state[4]! + e!) >>> 0;
    state[5] = (state[5]! + f!) >>> 0;
    state[6] = (state[6]! + g!) >>> 0;
    state[7] = (state[7]! + h!) >>> 0;
  }

  return [...state].map((word) => word.toString(16).padStart(8, '0')).join('');
}

/**
 * Canonical bytes of a fixture image artifact: an ASCII dimension header
 * followed by raw RGBA. Dimensions are inside the digest, so a buffer reshaped
 * without changing a single channel value still changes its identity.
 */
export function imageArtifactBytes(image: RgbaImage): Uint8Array {
  const header = utf8Bytes(`ppux-rgba8:${image.width}x${image.height}:`);
  const bytes = new Uint8Array(header.length + image.data.length);
  bytes.set(header);
  bytes.set(image.data, header.length);
  return bytes;
}

export function imageSha256(image: RgbaImage): string {
  return sha256Hex(imageArtifactBytes(image));
}

export function planSha256(plan: unknown): string {
  return sha256Hex(utf8Bytes(canonicalJson(plan)));
}
