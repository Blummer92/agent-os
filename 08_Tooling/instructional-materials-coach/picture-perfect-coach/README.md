# Picture Perfect Coach — PPUX-A / PPUX-C

Bounded Picture Perfect Coach implementation for #1183 and #1223.

## Scope

The active workflow still implements:

```text
Model -> Upload -> validation/result -> Review boundary
```

PPUX-C adds the Stage 4 prompt-card component and deterministic prompt-intent validation for approved modeled steps. It does **not** bypass or implement Stage 3 Review. `PromptCards` remains a bounded downstream component until a future Review slice supplies approved modeled steps.

This package does not implement tutorial review decisions, image generation, Ready/handoff behavior, Recorder conformance (RJ3), replay equivalence (RJ4), live Adobe execution, provider APIs, or any Notion/Drive/classroom write.

## Canonical boundaries

- #1134 remains the source for Recorder -> Teacher Modeling -> Picture Perfect ownership and provenance semantics.
- Teacher Modeling owns instructional disposition; this UI does not classify raw Recorder events into instructional truth.
- #955 remains the canonical provider-neutral ImageIntent owner. PPUX-C reuses its modules (identity/purpose, scene/context, visual direction, must-show/avoid controls, output direction) as a bounded consumer projection rather than defining a competing image-intent model.
- Provider-neutral means image-provider portability, not application neutrality. When approved evidence establishes `Adobe Express`, portable prompt meaning must preserve Adobe Express identity and recognizable evidence-supported application context.
- Application identity never authorizes invented UI. Unsupported labels, controls, locations, filenames, or states block the prompt rather than being inferred from branding.
- Prompt/image output is derived presentation evidence only and never becomes instructional/source evidence.
- RJ3/RJ4 are separate evidence states. `pending` and `unavailable` are rendered as not proven.

## Tutorial 0 regression fixture

`src/fixtures/tutorial0-recording.json` is privacy-safe synthetic Recorder data. Its companion evidence projection preserves completed #1134 authority-false semantics.

`src/fixtures/tutorial0-prompts.ts` adds the PPUX-C golden prompt fixture. Supported prompt cards preserve `application: Adobe Express` for the organized location, Create new file, and Square/Landscape/Portrait moments. The final favorite-food file state deliberately remains blocked because exact filenames/final arrangement are not established by approved evidence.

Negative tests cover generic/wrong-app substitution, missing application identity/context, unsupported UI detail, provider-adapter identity loss, and the blocked final-state case. No live Adobe or image provider is required.

## Commands

```bash
npm ci
npm run typecheck
npm run lint
npm test
npm run build
npm run guard
```

The package is designed for Node `>=22.12 <23`.

## Security / execution boundary

Normal source code contains no network, provider SDK, Puppeteer, or Playwright execution sink. `npm run guard` enforces that bounded surface. A passing package test proves only the local Picture Perfect transformation/presentation contract; it does not prove live Adobe pixel fidelity.
