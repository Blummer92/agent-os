# Picture Perfect Coach — PPUX-A / B / C / D / E

Bounded implementation package for the five-stage Picture Perfect authoring flow and its local browser acceptance suite.

## Scope

Implemented flow:

```text
Model -> Upload -> Review -> Prompts -> Ready
```

Stage 5 Ready performs deterministic local preflight and can generate a local implementation acceptance / GitHub handoff packet. It does **not** call GitHub or authorize implementation.

PPUX-E adds Playwright acceptance against the actual Vite application. It proves the privacy-safe Tutorial 0 journey and required fail-closed browser cases without navigating the real Adobe product or any external provider.

This package does not perform image generation, provider APIs, live Adobe/browser replay, GitHub branch/PR creation, merge, issue closure, Notion/Drive/classroom writes, or production activation.

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

## UI-claim evidence boundary (PPUX-F1)

**Picture Perfect cannot currently produce a ready software-interface visual, by design.** A frame that shows the real application interface may only be produced from approved captured screen evidence. No capture evidence is bound yet — that is PPUX-F2 — so every software-interface frame resolves to `blocked` with the machine-readable reason `visual-evidence-missing` rather than emitting a prompt that would have an image model reconstruct the interface.

`uiEvidence.ts` derives UI claims from the approved recording only, in two kinds: `accessible-name` (an `aria/...` selector) and `entered-value` (a `change` value). Semantic modeling fields such as a candidate `target` are instructional descriptors and are never UI evidence — `Square project` is not the recorded label `Square`. Every claim is bound to the source state it was observed at and to that action's identity (`source_fingerprint`), whose canonicalization is byte-compatible with `capture/safe_recording.mjs` so PPUX-F2 can join without retrofitting.

Rules enforced: authoring cannot supply or widen supported UI evidence; a claim observed at one action cannot authorize another (state locality); details observed at separate states are not co-visible in one frame; combining reviewed steps widens scope without flattening action-local evidence; a matching `source_index` with a mismatched `source_fingerprint` fails closed; the software-interface determination is derived, and an author may raise it but never lower it; a blocked card exposes no portable prompt and no copy affordance. Card runtime state stays binary (`ready | blocked`), with nuance in `blockerReasons`.

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

## Browser acceptance

`playwright.config.ts` starts the local Vite application on loopback and runs Chromium with one deterministic worker. The suite in `e2e/` drives the actual upload input, Review controls, prompt cards, Ready preflight, and local handoff packet.

The acceptance suite covers the Tutorial 0 happy path plus malformed JSON, off-approved-origin navigation, missing Teacher Modeling evidence, source mismatch, unresolved Review, provider-neutral/application-identity behavior, and the non-authorizing prompt/handoff boundary.

Playwright screenshots and video are disabled so acceptance does not create unnecessary visual artifacts. Traces are retained only on failure. Browser acceptance is local application testing, not live Adobe replay.

## Tutorial 0 fixture

The privacy-safe Tutorial 0 fixture runs through the real evidence -> Review -> Prompt -> Ready derivation and preserves Adobe Express identity because approved evidence carries it.

Its authored UI text was corrected against the recording under PPUX-F1: the folder is `Tutorial 0 - Organize My Files` (never `Tutorial 0 - My Favorite Food`), the control is `Create new` (never `Create new file`), and the landscape frame claims only `Landscape` because `Square` and `Portrait` belong to other steps. Every Tutorial 0 frame then blocks for want of screen evidence, which is the correct outcome; the recording and evidence fixtures are source evidence and are never edited to make authored prompt content validate.

## Commands

```bash
npm ci
npx playwright install chromium
npm run typecheck
npm run lint
npm test
npm run build
npm run guard
npm run test:e2e
```

The package is designed for Node `>=22.12 <23`, matching the adjacent capture tool runtime contract.

## Security / execution boundary

Normal application source contains no network, provider SDK, Puppeteer, GitHub API, Notion, or Drive execution sink. Playwright exists only in the package's test/development surface and drives the local Vite app. `npm run guard` enforces the bounded production surface. Passing tests prove local Picture Perfect transformation, presentation, deterministic preflight, packet generation, and browser UX acceptance; they do not prove live Adobe fidelity, image-provider output, or GitHub execution.