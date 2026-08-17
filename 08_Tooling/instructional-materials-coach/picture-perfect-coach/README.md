# Picture Perfect Coach — PPUX-A / PPUX-C

Bounded implementation package for the Picture Perfect Coach shell and prompt-card flow.

## Scope

Implemented slices:

```text
PPUX-A: Model -> Upload -> validation/result -> Review boundary
PPUX-C: approved modeled steps -> Prompt Cards -> future Ready boundary
```

This package does not implement Stage 3 Review decisions, Stage 5 Ready/handoff behavior, image generation, provider APIs, live Adobe execution, or Notion/Drive/classroom writes.

## Canonical boundaries

- #1134 remains the source for Recorder -> Teacher Modeling -> Picture Perfect ownership and provenance semantics.
- Teacher Modeling owns instructional disposition; this UI does not classify raw Recorder events into instructional truth.
- #955 remains the canonical provider-neutral ImageIntent owner; this package consumes that intent seam and does not define a competing image-intent framework.
- For software tutorials, provider-neutral means image-provider-neutral, not application-neutral.
- Application identity fidelity does not authorize invention of controls, labels, locations, or states absent from approved evidence.
- RJ3/RJ4 are separate evidence states. `pending` and `unavailable` are rendered as not proven.
- TypeScript interfaces in this package are bounded consumer projections only, not authoritative replacements for the GitHub/Python contracts.

## Application-fidelity contract

For an Adobe Express modeled tutorial, a complete portable prompt must preserve `application: Adobe Express`, recognizable Adobe Express context, the intended target/state, must-show constraints, and approved provenance.

Generic creative-app UI, another application, missing application context, provider-specific canonical syntax, or unsupported UI detail fails closed. Provider adapters may alter execution syntax/settings only and may not remove application identity, target state, or must-show evidence.

## Tutorial 0 fixture

The privacy-safe Tutorial 0 fixtures cover the coherent Adobe Express sequence without promoting raw Recorder segmentation into student lessons. Supported prompt cards preserve Adobe Express identity. Unsupported details remain blocked rather than invented.

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

Normal source code contains no network, provider SDK, Puppeteer, or Playwright execution sink. `npm run guard` enforces that bounded surface. A passing package test proves only local Picture Perfect UI transformation and presentation behavior; it does not prove live Adobe fidelity or image-provider output.
