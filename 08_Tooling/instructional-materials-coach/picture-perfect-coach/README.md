# Picture Perfect Coach — PPUX-A / B / C / D

Bounded implementation package for the five-stage Picture Perfect authoring flow.

## Scope

Implemented flow:

```text
Model -> Upload -> Review -> Prompts -> Ready
```

Stage 5 Ready performs deterministic local preflight and can generate a local implementation acceptance / GitHub handoff packet. It does **not** call GitHub or authorize implementation.

This package does not perform image generation, provider APIs, live Adobe/browser execution, GitHub branch/PR creation, merge, issue closure, Notion/Drive/classroom writes, or production activation.

## Canonical boundaries

- #1134 remains the source for Recorder -> Teacher Modeling -> Picture Perfect ownership and provenance semantics.
- Teacher Modeling owns instructional disposition; this UI does not classify raw Recorder events into instructional truth.
- #955 remains the canonical provider-neutral ImageIntent owner; this package consumes that intent seam and does not define a competing image-intent framework.
- TypeScript interfaces are bounded UI/consumer projections only.
- For software tutorials, provider-neutral means image-provider-neutral, not application-neutral.
- Application identity fidelity does not authorize invention of controls, labels, locations, or states absent from approved evidence.
- Prompt/image output remains presentation guidance, never source instructional evidence.

## Stage 4 prompt boundary

`projectReviewedTutorialToPromptCards` consumes the PPUX-B `ReviewedTutorialProjection` / `ReviewedStepProjection` boundary and produces bounded `PromptCardModel[]`. Application identity comes only from approved `modeled_application`; missing identity blocks software-UI prompt output rather than being inferred.

## Stage 5 Ready boundary

`runReadyPreflight` in `preflight.ts` deterministically checks the bounded evidence needed for an implementation handoff, including source identity/fingerprint, reviewed-step provenance, explicit review decisions, modeled application identity, prompt validity, golden fixture identity, required tests, Definition of Done, and architecture-decision status.

`createGitHubHandoffPacket` returns a local `picture-perfect-ready-v1` packet only when all required rows pass. The packet preserves source/provenance, retained and excluded review outcomes, prompt requirements, provider-adapter boundaries, tests, non-goals, and Definition of Done, and always states:

```text
execution_authorized: false
```

Invariant:

```text
ready_for_handoff
!= implementation_authorized
!= GitHub write authorized
!= external write authorized
```

The teacher-facing `Create GitHub Handoff` button only renders the packet locally for review/copy. It has no GitHub client or external-write path.

## Tutorial 0 fixture

The privacy-safe Tutorial 0 fixture runs through the real evidence -> Review -> Prompt -> Ready derivation. Supported prompt cards preserve Adobe Express identity because approved evidence carries it. The Ready packet preserves the coherent reviewed sequence, combined-step provenance, excluded incidental step, recording identity/fingerprint, and provider-neutral prompt constraints.

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

Normal source code contains no network, provider SDK, Puppeteer, Playwright, GitHub API, Notion, or Drive execution sink. `npm run guard` enforces the bounded surface. Passing tests prove only local Picture Perfect transformation, presentation, deterministic preflight, and packet generation; they do not prove live Adobe fidelity, image-provider output, or GitHub execution.
