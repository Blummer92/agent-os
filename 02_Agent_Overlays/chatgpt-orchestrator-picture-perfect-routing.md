# ChatGPT Orchestrator Picture Perfect Routing

This detail file is part of `chatgpt-orchestrator.md`. It owns only the bounded routing rule for requests that resolve to an existing Picture Perfect / PPUX tutorial prompt artifact. It does not define a second request interpreter, image-intent framework, tutorial model, or execution path.

## Canonical Capability Boundary

- Route through the registered Instructional Materials Coach and the existing Picture Perfect package at `08_Tooling/instructional-materials-coach/picture-perfect-coach/`.
- Consume the existing reviewed tutorial -> PPUX-C prompt-card path. Do not duplicate the prompt engine or Tutorial 0 fixture.
- Treat Picture Perfect, PPUX, an existing Picture Perfect tutorial, or tutorial image prompts derived from approved Picture Perfect modeling evidence as capability identity supplied by canonical request/context evidence, not as a new phrase-matching language.
- Preserve the canonical five-stage flow: `Model -> Upload -> Review -> Prompts -> Ready`.

## Prompt Routing Contract

When the resolved request asks for image prompts for an existing Picture Perfect tutorial:

1. Prefer canonical PPUX prompt cards over generic image-prompt authoring.
2. Resolve Tutorial 0 through the existing Tutorial 0 reviewed fixture and prompt-card data.
3. Preserve modeled application identity end to end. For Tutorial 0, supported prompt cards remain Adobe Express prompts.
4. Preserve evidence-supported `mustShow` UI details and existing PPUX-C provider-neutral prompt constraints.
5. Preserve blocked prompt cards as blocked/manual-review outcomes. Never replace missing evidence with plausible controls, labels, locations, workflow steps, filenames, or final states.
6. If the requested tutorial or prompt artifact cannot be resolved from canonical context, fail visibly or route to review. Do not silently fall back to generic generation.
7. Prompt derivation creates no image-provider execution authority. Generate or edit an image only through a separately authorized provider-execution request.

## Tutorial 0 Regression

The intent represented by:

`Show me what tutorial 0 looks like in image prompts`

must resolve to Picture Perfect / PPUX when Tutorial 0 is the known active Picture Perfect tutorial. The user-visible prompt source is the existing Tutorial 0 PPUX prompt-card path: three ready Adobe Express prompt cards are available, while unsupported final-state details remain blocked.

Equivalent requests such as `Picture Perfect Tutorial 0 prompts`, `Tutorial 0 image prompts` in known Picture Perfect context, and `show me Tutorial 0 prompts` follow the same route.

## Negative Boundaries

- A generic image-generation or generic prompt-authoring request with no resolved Picture Perfect capability remains on the normal generic path.
- An unknown or ambiguous tutorial does not produce fabricated PPUX output.
- Missing approved application identity remains blocked under the existing PPUX-C contract.
- Unsupported UI details remain blocked rather than rewritten into plausible Adobe controls.
- Routing alone does not call an image provider, browser, Adobe Express, GitHub, Notion, Drive, or another external system.
- Routing does not mutate classroom artifacts, governed state, readiness, approval, or source-of-truth records.

## Ownership

ChatGPT Orchestrator owns request routing. Instructional Materials Coach owns the Picture Perfect prompt-artifact capability. QA / Test Agent owns regression evidence. GitHub Service Agent remains the sole repository writer for changes to this contract.
