# #2525 — Governed PPUX prompt-projection transport

## Purpose

Register the existing #2524 Picture Perfect prompt-projection entrypoint as a distinct bounded governed operation without changing the existing validation-only `ppux-picture-perfect-ts-vitest` identity.

## Fixed operation contract

Operation identity: `ppux-picture-perfect-prompt-projection`

The operation is fixed to:

- entrypoint: `src/promptProjectionEntrypoint.ts` / `projectTutorialPromptCards(...)`;
- working directory: `08_Tooling/instructional-materials-coach/picture-perfect-coach`;
- runtime family: qualified Node 22;
- exact repository branch and SHA supplied by the governed request;
- bounded `picture-perfect-prompt-projection-input-v1` input;
- structured `picture-perfect-prompt-projection-result-v1` output.

The existing `ppux-picture-perfect-ts-vitest` identity remains validation-only and continues to execute its fixed six Vitest targets.

## Input boundary

The operation consumes only the already-resolved #2524 projection envelope. It does not accept free-form shell/argv, arbitrary repository paths, arbitrary modules, raw chat prose, raw Notion JSON, provider instructions, or browser instructions.

Tutorial 0 may be used as regression evidence only and must never replace a requested tutorial/handoff identity.

## Result envelope

Transport/execution evidence is kept separate from the canonical PPUX domain result. A successful recorder preserves:

- repository, issue, branch, and exact tested SHA;
- operation identity;
- bounded request/input identity;
- cleanup evidence;
- the exact structured #2524 projection result, including route/source identity, application identity, ready/blocked prompt-card state, blockers, provenance, and all-false authority fields.

The PPUX payload is never reconstructed by Python or Workflow Scheduler.

## Output bounds

The canonical projection payload is not stored in the existing 4096-character diagnostic tail. Diagnostics remain diagnostics.

The operation admits a finite structured payload with explicit byte/card/field limits. An output that exceeds the admitted bound fails closed with a finite `projection-output-oversize` reason. Partial or tail-truncated JSON is never returned as canonical projection evidence.

A larger valid projection must be emitted as a separately bounded content-addressed artifact referenced by the result envelope rather than silently truncated.

## Artifact egress

Reuse the existing governed ingress artifact publication/retrieval pattern. Artifact evidence binds the exact execution SHA, operation identity, input identity, projection payload/reference, cleanup state, and all-false authority states.

Do not place credentials, browser-profile material, sensitive screenshots, unrestricted Notion data, or provider output in ordinary artifacts or logs.

## Authority

Transport success does not imply PPUX Ready, provider execution, production authorization, publication, classroom readiness, merge authority, or external-write authority. This operation performs no provider, browser, Notion, Drive, classroom, or other external write.

## Rollback

Remove only the `ppux-picture-perfect-prompt-projection` registration, structured recorder/transport bindings, corresponding tests, and this documentation. Leave the existing validation profile and governed transport unchanged.
