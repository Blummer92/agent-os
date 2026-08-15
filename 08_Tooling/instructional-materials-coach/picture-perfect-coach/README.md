# Picture Perfect Coach — PPUX-A

Bounded first implementation slice for #1183.

## Scope

This package implements only:

```text
Model -> Upload -> validation/result -> Review boundary
```

It does not implement tutorial review decisions, prompt generation, image generation, Ready/handoff behavior, Recorder conformance (RJ3), replay equivalence (RJ4), live Adobe execution, or any Notion/Drive/classroom write.

## Canonical boundaries

- #1134 remains the source for Recorder -> Teacher Modeling -> Picture Perfect ownership and provenance semantics.
- Teacher Modeling owns instructional disposition; this UI does not classify raw Recorder events into instructional truth.
- #955 remains the canonical provider-neutral ImageIntent owner; this package does not define an image-intent model.
- RJ3/RJ4 are separate evidence states. `pending` and `unavailable` are rendered as not proven.
- TypeScript interfaces in this package are bounded consumer projections only, not authoritative replacements for the GitHub/Python contracts.

## Offline synthetic fixture

`src/fixtures/tutorial0-recording.json` is privacy-safe synthetic Recorder data. Its companion evidence projection uses the completed #1134 shape and preserves authority-false semantics. Unknown recordings fail closed because this first slice has no connected analysis service and must not guess instructional counts.

The synthetic workflow covers organizing the Adobe Express location, creating/opening Tutorial 0, square/landscape/portrait file creation, favorite-food reference imagery, naming/organization, final-location verification, and one removable incidental key event. It contains no authentic Adobe account data or student data.

## Commands

```bash
npm install
npm run typecheck
npm run lint
npm test
npm run build
npm run guard
```

The package is designed for Node `>=22.12 <23`, matching the adjacent capture tool runtime contract.

## Security / execution boundary

Normal source code contains no network, provider SDK, Puppeteer, or Playwright execution sink. `npm run guard` enforces that bounded surface. A passing package test proves only the local Picture Perfect UI transformation and presentation behavior; it does not prove live Adobe fidelity.
