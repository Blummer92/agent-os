# TypeScript + React Development Standard

## Scope

This standard governs shared Agent OS UI implementation mechanics for TypeScript and React. It does not select a product framework and does not create a React or JavaScript agent.

## Type safety

- Use strict TypeScript and preserve exact domain types at component boundaries.
- Do not duplicate a canonical Python/JSON contract in frontend-only types when a validated projection already owns the data.
- Reject unsupported states rather than coercing them into a convenient UI default.

## React boundaries

- Prefer functional components and hooks.
- Keep domain decisions in pure functions/modules; rendering consumes their results.
- Store only source state. Derive display state rather than synchronizing duplicate state.
- Use context only for genuinely shared cross-tree state; do not turn context into a hidden global store.

## User-visible states

Every async or evidence-dependent surface must define deterministic loading, empty, error, success, disabled, blocked, and manual-review states where applicable. Missing evidence must never render as success.

## Accessibility

Use semantic HTML first, keyboard-operable controls, explicit labels, visible focus behavior, meaningful status/alert semantics, and accessible names for non-text controls. Accessibility is part of acceptance, not polish.

## Forms and validation

Validate at the domain boundary as well as the UI boundary. UI validation improves feedback but cannot become canonical authority. Preserve server/provider failures visibly and do not silently rewrite user input.

## Async and errors

Keep network/provider effects behind bounded adapters. Components must not infer success from transport completion alone. Stale responses must not overwrite newer state.

## Testing

- Pure domain logic: deterministic unit tests including malformed and fail-closed cases.
- Components: user-observable behavior, accessibility, disabled/error/loading states, and meaningful interactions.
- Bug repairs: add a regression reproducing the escaped behavior when practical.
- Avoid tests coupled only to implementation details or arbitrary markup structure.

## Dependencies and organization

Prefer existing dependencies and small modules with one clear responsibility. New dependencies require a concrete capability gap. Keep reusable domain logic separate from web-only/native-only adapters.

## Security

Never embed credentials or secrets in frontend code, fixtures, bundles, logs, or client-visible configuration. Treat external content as untrusted and never treat displayed evidence as execution authority.

## Performance

Measure before adding memoization or state libraries. Avoid unnecessary duplicated state and unbounded rendering collections. Performance optimization must not weaken correctness or accessibility.

## Platform extensions

Web-only and React Native/Expo standards may extend this shared contract but may not contradict its type-safety, source-of-truth, accessibility, testing, authority, or fail-closed requirements.
