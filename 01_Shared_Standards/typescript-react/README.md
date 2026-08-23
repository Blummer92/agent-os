# TypeScript + React Shared Development Standard

## Purpose

Define the common Agent OS engineering baseline for user interfaces built with
TypeScript and React. This standard is technology guidance, not an executable
agent and not a framework mandate.

GitHub remains the source of truth for this standard. Repository implementation
remains owned by the GitHub Service Agent; QA / Test Agent owns independent
validation evidence.

## Scope Boundary

This file governs behavior shared by React web applications and React Native /
Expo applications. Web-only browser behavior and native-only platform behavior
belong in narrower follow-up standards.

Do not require Next.js, Vite, Expo, React Native, a component library, a state
library, or a form library globally. Select them only when the bounded project
contract requires them.

## Canonical Contract Boundary

TypeScript types and React models must not silently become a second source of
truth for a canonical Agent OS Python, JSON, or schema-owned contract.

When an authoritative contract already exists:

1. consume a validated projection, generated type, or explicit adapter;
2. preserve canonical field meanings, finite states, identity, and authority;
3. reject or surface unsupported values rather than guessing replacements; and
4. keep presentation-only state separate from authoritative domain state.

## TypeScript

- Enable strict type checking for new maintained TypeScript packages unless a
  narrower inherited project contract documents a compatibility exception.
- Prefer explicit domain types over `any`; use `unknown` at untrusted boundaries
  and narrow it before use.
- Model finite states with discriminated unions or equivalent exhaustive types.
- Avoid non-null assertions when absence is a legitimate runtime state.
- Keep external input parsing and validation at the boundary rather than
  spreading casts through components.
- Prefer immutable values and readonly interfaces when mutation is unnecessary.

## React Components And Hooks

- Use functional components and hooks for new React work.
- Keep components focused on one clear rendering or interaction responsibility.
- Extract reusable domain logic from rendering when it can be tested without the
  component tree.
- Keep hooks deterministic with explicit dependencies; do not suppress hook
  dependency warnings merely to silence tooling.
- Use effects for synchronization with external systems, not for ordinary derived
  state.
- Prefer composition to deeply configurable multipurpose components.

## Props, State, Derived State, And Context

- Keep state as local as practical and lift it only when multiple consumers need
  one shared owner.
- Derive values during render when they are a pure function of current props or
  state instead of duplicating them into state.
- Do not mirror server or canonical domain state into additional writable local
  copies without an explicit editing/draft boundary.
- Use context for stable cross-tree concerns, not as a default replacement for
  ordinary props or a general global store.
- Model loading, empty, error, success, disabled, and permission-denied states
  explicitly when they can occur.

## Async Data And Errors

- Treat network, storage, provider, and parsing failures as expected states.
- Distinguish initial loading from background refresh when the UX differs.
- Never render stale or partial data as confirmed current data without an
  explicit state indicating that condition.
- Keep retry behavior bounded and user-visible when retry has side effects or
  material cost.
- Log or surface diagnostics without exposing secrets or sensitive payloads.

## Forms And Validation

- Separate input state, validation state, and mutation/submission state.
- Validate untrusted values at the owning boundary; client validation improves
  UX but does not replace authoritative server/domain validation.
- Preserve user input when a recoverable submission fails.
- Prevent duplicate submissions when the operation is not idempotent.
- Associate validation messages with the relevant control and provide a useful
  summary when several errors must be reviewed together.

## Accessibility

Accessibility is a first-class implementation requirement.

- Use semantic elements and native platform controls before recreating behavior.
- Every interactive control must be keyboard/focus operable on platforms where
  keyboard interaction applies.
- Provide accessible names, labels, instructions, status announcements, and
  error associations appropriate to the platform.
- Do not rely on color alone to communicate required state.
- Preserve usable focus order and visible focus indication.
- Respect reduced-motion preferences for non-essential animation where the
  platform exposes them.
- Test important user flows with accessibility-oriented queries and assertions,
  not only CSS selectors or implementation details.

## Testing

Test behavior at the lowest useful layer while preserving user-visible coverage.

- Pure domain functions: deterministic unit tests.
- Reusable hooks/adapters: focused tests around their public contract.
- Components: render and interact through roles, labels, text, and user actions.
- Async states: cover loading, empty, success, error, retry, and stale states that
  the component can actually reach.
- Forms: cover validation, submission, duplicate prevention, and recoverable
  failure behavior.
- Critical flows: use integration or end-to-end coverage when correctness depends
  on component composition, routing, browser/native behavior, or real boundaries.
- Avoid snapshot-only proof for interactive behavior.

Issue-required typecheck, lint, unit, build, accessibility, or end-to-end commands
remain pre-PR developer-loop gates when the governing issue names them. Final
Ready-for-Review still follows the canonical exact-head validation policy.

## Dependencies And Versions

- Prefer the smallest maintained dependency that satisfies a demonstrated need.
- Check license, maintenance state, security posture, platform compatibility, and
  bundle/runtime cost before adoption when material.
- Reuse an existing repository dependency when it already satisfies the need and
  does not violate the project contract.
- Pin or range dependencies according to the package's existing lockfile and
  repository dependency policy; do not introduce a second package manager merely
  for convenience.
- Treat major dependency upgrades as compatibility changes when public behavior,
  build output, or runtime assumptions may change.

## Organization And Naming

- Organize by stable product/domain responsibility before creating deep technical
  layer trees.
- Keep component, hook, utility, test, and fixture names descriptive of behavior.
- React components use PascalCase; hooks use `use...`; ordinary functions and
  variables use the repository's TypeScript camelCase convention.
- Co-locate narrowly owned tests and support files when the package convention
  favors it; shared primitives should live in one clearly owned shared location.
- Avoid generic dumping grounds such as `utils` or `helpers` when a domain owner
  can be named more precisely.

## Security And Secrets

- Never place secrets, service credentials, private keys, or privileged tokens in
  browser/native bundles or committed client configuration.
- Treat URL parameters, storage values, postMessage/native bridge payloads,
  clipboard data, and provider responses as untrusted input.
- Escape/render user-controlled text through framework-safe primitives; do not
  introduce raw HTML rendering without a bounded sanitization contract.
- Authorization decisions belong to the canonical owning service/domain; hiding
  a control is not authorization enforcement.

## Performance

- Measure before adding memoization, virtualization, caching, or state machinery.
- Avoid expensive work during render when it can be computed once at the correct
  boundary.
- Use memoization only when identity stability or measured render cost justifies
  the added complexity.
- Keep list keys stable and domain-derived; do not use array indexes when identity
  can change through insertion, removal, or reorder.
- Lazy-load large optional surfaces when it materially improves the user path and
  preserves error/loading accessibility.

## Documentation

A maintained UI package should document its runtime/build commands, supported
platform target, important architecture boundaries, state/data ownership,
required environment inputs, test commands, and any deliberate deviation from
this standard.

## Web And Native Extensions

Future web-only and React Native/Expo standards may tighten this baseline for
platform-specific routing, rendering, accessibility APIs, persistence, testing,
bundling, and deployment. They must inherit this shared contract rather than
copying it into competing conventions.

If a platform extension conflicts with this shared standard, resolve the
ownership/compatibility decision in GitHub rather than silently overriding the
shared rule.

## Non-Goals

This standard does not create a React/JavaScript agent, production application,
framework selection, design system, state library, API architecture, deployment
policy, or external-write authority.

## Version

0.1.0
