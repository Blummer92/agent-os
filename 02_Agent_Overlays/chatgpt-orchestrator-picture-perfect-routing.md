# ChatGPT Orchestrator Picture Perfect Routing

This detail file is part of `chatgpt-orchestrator.md`. It owns only the bounded routing rule for requests that canonical request/context evidence resolves to an existing Picture Perfect / PPUX tutorial prompt artifact. It does not define a second request interpreter, phrase matcher, image-intent framework, tutorial model, or execution path.

## Canonical Capability Boundary

- Consume canonical `request-interpretation-v1` and current conversation/context evidence; example utterances below are regression inputs, not a new phrase-matching vocabulary.
- Route through the registered Instructional Materials Coach and the existing Picture Perfect package at `08_Tooling/instructional-materials-coach/picture-perfect-coach/`.
- Consume the existing reviewed tutorial -> PPUX prompt-card path. Do not duplicate the prompt engine, Tutorial 0 fixture, capture binding, or ImageIntent contract.
- Preserve the canonical five-stage flow: `Model -> Upload -> Review -> Prompts -> Ready`.

## Prompt Routing Contract

When the resolved request asks for image prompts for an existing Picture Perfect tutorial:

1. Prefer canonical PPUX prompt-card output over generic image-prompt authoring.
2. Resolve Tutorial 0 through the existing reviewed Tutorial 0 fixture and prompt-card projection when Tutorial 0 is the active known Picture Perfect tutorial.
3. Return the current canonical PPUX state without rewriting it. Preserve ready cards, blocked cards, blocker reason codes, teacher-facing explanations, application identity, provenance, and approved capture evidence exactly as the capability exposes them.
4. Do not pin a ready-card count, UI-label expectation, or permanent ready/blocked assumption in routing policy or tests. PPUX fidelity children may legitimately change card state while the routing contract remains stable.
5. Preserve blocked outcomes visibly. If PPUX returns no ready output, say so with the canonical reason; that is a valid routed result, not permission to reconstruct the tutorial generically.
6. Never replace missing evidence with plausible controls, labels, locations, workflow steps, filenames, states, or reconstructed software UI.
7. If the requested tutorial or prompt artifact cannot be resolved from canonical context, fail visibly or route for review. Do not silently fall back to generic generation.
8. Prompt derivation creates no image-provider execution authority. Provider execution requires a separate explicit request and its own authorization/capability path.

## Tutorial 0 Regression Inputs

These user intents must resolve to Picture Perfect / PPUX when Tutorial 0 is the known active Picture Perfect tutorial:

- `Show me what tutorial 0 looks like in image prompts`
- `Picture Perfect Tutorial 0 prompts`
- `Tutorial 0 image prompts`
- `show me Tutorial 0 prompts`

The regression asserts routing provenance and state fidelity only. It does not assert a card count or specific interface text.

## Negative Boundaries

- A generic image-generation or generic prompt-authoring request with no resolved Picture Perfect capability remains on the normal generic path.
- An unknown or ambiguous tutorial does not produce fabricated PPUX output.
- Missing approved application identity or visual evidence remains blocked when the canonical PPUX contract says it is blocked.
- Blocked reason codes and teacher-facing explanations are not filtered out by routing.
- A fully blocked PPUX result does not trigger generic fallback and is not presented as PPUX success.
- Routing alone does not call an image provider, browser, Adobe Express, GitHub, Notion, Drive, or another external system.
- Routing does not mutate classroom artifacts, governed state, readiness, approval, or source-of-truth records.

## Ownership

ChatGPT Orchestrator owns request routing. Instructional Materials Coach owns the Picture Perfect prompt-artifact capability. QA / Test Agent owns regression evidence. GitHub Service Agent remains the sole repository writer for changes to this contract.
