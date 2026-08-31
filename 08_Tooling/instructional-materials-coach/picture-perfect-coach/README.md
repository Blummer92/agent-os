# Picture Perfect Coach — PPUX-A / B / C / D / E / F1 / F2

Bounded implementation package for the five-stage Picture Perfect authoring flow and its local browser acceptance suite.

## Scope

Implemented flow:

```text
Model -> Upload -> Review -> Prompts -> Ready
```

Stage 5 performs deterministic local preflight and can generate a local implementation handoff packet. It does not call GitHub or authorize implementation. Playwright drives only the local Vite app; no live Adobe, provider, Notion, Drive, classroom, or production write is required.

## Canonical boundaries

- #1134 owns Recorder -> Teacher Modeling -> Picture Perfect ownership/provenance.
- #955 owns provider-neutral ImageIntent; this package does not create a competing intent contract.
- `software-tutorial-capture-v1` remains read-only capture evidence owned by the adjacent capture package.
- `curriculum-artifact-manifest-v1` owns stored asset identity, privacy, rights, lifecycle, and classroom readiness.
- `curriculum-visual-asset-compatibility-v2` owns suitability; `interface-capture` is accepted only with `screen-capture` medium and an eligible non-stale record.
- TypeScript types here are bounded consumer projections, not new canonical schemas.
- Prompt/image output is presentation guidance, never source instructional evidence.

## F1 UI-claim boundary

`uiEvidence.ts` derives UI claims only from approved Recorder evidence: accessible names and entered values. Semantic targets, titles, student-action text, branding, and tutorial names cannot manufacture UI evidence.

Every claim carries `source_index`, `source_fingerprint`, and recording identity. Evidence is state-local; distinct states are not treated as co-visible. With no approved capture bundle, a software-interface frame remains `blocked`, exposes no portable prompt, and never falls back to generative reconstruction.

## F2 captured-screen binding

`captureEvidence.ts` consumes `software-tutorial-capture-v1` read-only and requires full action identity:

```text
recording_sha256 + source_index + source_fingerprint
```

Array position alone never binds. Capture preflight must be exactly `valid`; recording or fingerprint mismatch, missing roles, stale compatibility, unresolved privacy, ineligible assets, or missing evidence fail closed.

Screen-state roles remain distinct:

```text
action        -> screenshot_before
result        -> screenshot_after
action+result -> both roles independently
```

A bound state keeps the exact action-local target geometry. Combined reviewed steps never union geometry or UI claims across actions. All requested UI claims for one required screen state must be supported by one approved screenshot.

Stored screenshot identity is carried by the existing compatibility `manifest_reference` and `asset_reference`; F2 does not create an asset registry or reference contract. The local projection consumes already-validated ArtifactManifest privacy/rights/readiness and compatibility-v2 cohesion/freshness evidence.

A capture-backed interface card may reach `ready`, but its portable instruction says to use the approved capture as the base visual and forbids redrawing, reconstructing, or inventing interface content. A deprecated opaque `capturedScreenRef` string is non-authoritative and cannot unlock the gate.

## Tutorial 0 synthetic proof

The privacy-safe Tutorial 0 fixture has two projections:

- `tutorial0PromptCards` supplies no capture and remains the F1 fail-closed regression path.
- `tutorial0CapturedPromptCards` binds synthetic before/after evidence through F2 and proves a truthful offline Ready path.

The synthetic fixture does **not** prove live Adobe selector stability, geometry fidelity, screenshot fidelity, authentication persistence, replay reliability, or screen accuracy. Those claims remain in the separately gated empirical lane under #931.

The supported synthetic cards demonstrate a result-state location frame, an action-state `Create new` frame, and an `action+result` `Landscape` frame. The unsupported final-state card still blocks rather than inventing filenames or arrangement.

## Stage 5 Ready boundary

`runReadyPreflight` requires every software-interface card to carry approved role-preserving capture evidence and to pass the provider-neutral/application boundary. `createGitHubHandoffPacket` preserves action/result evidence, action identity, manifest/asset references, and geometry while retaining:

```text
execution_authorized: false
```

Invariant:

```text
ready_for_handoff != implementation_authorized != external_write_authorized
```

## Authorized-overlay integrity (#1495)

`overlayIntegrity.ts` is Gate C. Gate A asks whether the pixels match the plan and Gate B asks whether the provenance report can be believed; Gate C asks whether an element was allowed to be drawn at all:

```text
only the resolved plan authorizes PPUX-added pixels
```

A zero-overlay plan authorizes zero PPUX overlay pixels, and an artifact-only output gains no editor window, layer panel, toolbar, control, tutorial UI, or explanatory framing — the exact-composite plan has no record that authorizes application chrome, so it is unrepresentable rather than merely discouraged.

Conversation history, tutorial-looking source state, application identity, procedure provenance, provider inference, and provider helpfulness are enumerated as authority claims only so a refusal can name which leakage class it rejected. None of them authorizes a pixel.

The declared element inventory is evidence, never authority: it can only convict. A declared element with no plan record is unauthorized, a plan overlay with no declared element is an incomplete execution, and an executor's self-report — narrative, step trace, recovered spotlight estimate, or an acknowledgement that unrequested UI was added — is recorded verbatim and consulted for nothing.

Overlay masks are fixed by the plan before execution. An element drawn wider than its plan record cannot widen its own footprint, a report cannot widen the overlay bleed after output, and a plan edited after output breaks the #1484 plan digest. Planned target geometry stays tied to admitted geometry: a spotlight boundary must be the admitted target rect and an arrow tip must land inside it, so a neighbouring control fails. Arrows, badges, icons, and editor chrome already present in admitted source evidence remain source pixels.

There is no OCR, computer vision, model scoring, or editor-UI detection anywhere in this gate. #1484 exact-composite planning, execution, and validation are consumed unchanged; #1496 source admission, #1497 bounded fill, and #1501 procedure-grounded synthesis are not duplicated or widened.

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

The package targets Node `>=22.12 <23`. Repository structural and aggregate validation are also required before Ready-for-Review.

The governed developer-validation identity `ppux-picture-perfect-ts-vitest` (#1495) runs a fixed subset of this package's suite — `overlayIntegrity`, `exactComposite`, `exactCompositeSuite`, `framePlan`, `executorContract`, `provenanceValidator` — from repository-owned configuration only. It is documented in `08_Tooling/agent-os-execution-service/docs/HOST_RUNTIME_INSTALLATION.md`; it selects no argv, path, filter, or reporter, and it authorizes nothing.
