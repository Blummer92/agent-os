# React Web Development Standard

## Scope

This standard extends `typescript-react-development.md` for browser-facing React interfaces. It governs web-specific implementation and acceptance without selecting one framework for every product, creating a Web Agent, or redefining canonical backend contracts in TypeScript.

## Semantic web structure

- Use semantic HTML elements according to document and interaction meaning before adding generic containers or ARIA roles.
- Preserve a logical heading hierarchy, landmarks, labels, lists, tables, links, buttons, and form controls so browser and assistive-technology behavior remains native where possible.
- Use a button for an action and a link for navigation. Do not recreate native controls with clickable `div` or `span` elements.
- Add ARIA only when native HTML cannot express the required semantics; ARIA must not contradict native semantics.
- Keep document metadata, title, language, and meaningful page structure explicit when the product is document-like, public, or search-indexed.

## CSS and responsive layout

- Treat CSS as a first-class web implementation surface rather than an incidental React detail.
- Prefer mobile-first, content-driven layouts that remain usable across representative narrow, medium, and wide viewports.
- Use Flexbox for primarily one-dimensional alignment and Grid for genuinely two-dimensional layout; do not use absolute positioning as a general layout system.
- Prefer resilient sizing, wrapping, intrinsic layout, and bounded breakpoints over device-specific pixel assumptions.
- Preserve zoom, text resizing, reflow, and user font-size preferences. Do not make fixed dimensions the only path to readable content.
- Keep reusable design tokens separate from component-specific layout rules. Shared tokens may cross web/native boundaries when their meaning is genuinely platform-neutral; CSS implementation details remain web-owned.

## Keyboard, focus, and interaction

- Every interactive flow must be operable by keyboard when the underlying task is keyboard-applicable.
- Preserve visible focus indicators and predictable focus order. Do not remove outlines without an accessible replacement.
- Move focus programmatically only for a concrete interaction requirement such as opening a modal, restoring focus after dismissal, or announcing a newly active view.
- Modal dialogs must trap focus while active, expose an accessible name, support an appropriate dismissal path, and restore focus to a sensible originating control.
- Hover must never be the only way to reveal required information or controls.
- Pointer target behavior must not depend on precision that makes ordinary touch or alternative input impractical.

## Accessibility acceptance

Accessibility is part of implementation acceptance. At minimum, web work must consider:

- semantic structure and accessible names;
- keyboard-only completion of representative flows;
- visible focus and focus restoration;
- form labels, instructions, validation, and error association;
- status, alert, and live-region behavior where asynchronous changes need announcement;
- sufficient contrast and non-color-only meaning;
- zoom/reflow and representative responsive layouts;
- reduced-motion preferences when motion is non-essential;
- automated accessibility checks where useful, supplemented by behavioral tests for interactions automation cannot prove.

Do not claim WCAG conformance from automated checks alone. Product-specific conformance targets must be explicit when required.

## Forms and browser-native behavior

- Prefer native form controls and browser behaviors when they satisfy the interaction contract.
- Associate labels and help/error text programmatically with controls.
- Preserve useful browser behaviors such as form submission, autofill, input modes, validation hints, history, and navigation unless the product has an evidence-backed reason to override them.
- Client validation is user feedback, not canonical authority. Domain/server validation remains authoritative at its governed boundary.
- On submission failure, preserve user-entered values when safe and make the failure visible without implying success.

## Routing and navigation

- Choose routing complexity according to product needs. A bounded single-view client application does not require a full-stack framework solely to obtain routing.
- Browser history, deep links, refresh behavior, back/forward navigation, and direct-entry states must be intentional for routable interfaces.
- Navigation state must not silently diverge from the URL when the URL is part of the product contract.
- Protect route-level authorization at the authoritative backend boundary; hiding a client route or control is not access control.

## Rendering and framework selection

React is the shared UI foundation, but framework selection is evidence-driven.

### Prefer a bounded client build such as Vite when

- the product is primarily an authenticated or bounded client application;
- server rendering, static generation, server components, or framework-owned backend routes are not requirements;
- browser APIs and client-side interaction dominate the experience; and
- a smaller build/runtime surface reduces unnecessary complexity.

### Prefer a React framework with server/static rendering capabilities when

- SEO or first-load document delivery materially depends on server/static rendering;
- route-level data loading or server-owned rendering is a real requirement;
- the product needs framework-provided server capabilities that would otherwise be rebuilt locally; or
- deployment architecture already establishes that framework as the bounded supported path.

Do not choose Next.js, Vite, or another framework globally by convention alone. Record the requirement that justifies the choice when it materially affects architecture.

### Prefer ordinary web primitives over React Native Web when

- semantic HTML or document structure is important;
- browser-native forms, links, tables, media, or accessibility behavior are central;
- CSS capabilities are materially simpler or more maintainable than cross-platform abstraction;
- SEO, metadata, browser APIs, or progressive enhancement matter; or
- sharing rendering code would reduce web correctness, accessibility, performance, or maintainability.

React Native Web remains an option for genuinely application-like shared components. One codebase is not a goal by itself.

## Progressive enhancement and browser compatibility

- Use progressive enhancement when a useful baseline can remain available without optional client behavior.
- Establish the supported browser matrix from product/user requirements rather than assuming every historical browser or only the latest browser.
- Prefer standards-based APIs with stable support. Add polyfills or compatibility dependencies only for a demonstrated support gap.
- Feature-detect optional browser capabilities where appropriate; do not infer support from user-agent strings when capability detection is sufficient.
- Unsupported required capabilities must produce a clear bounded state rather than silent malfunction.

## Performance

- Treat performance as observable product behavior: measure before adding optimization machinery.
- Keep initial JavaScript and CSS proportional to the product; avoid importing large libraries for narrow capabilities already provided by the platform or existing dependencies.
- Split code or lazy-load routes/components when measurement or obvious payload boundaries justify it, while preserving accessible loading and error states.
- Size and encode images appropriately, reserve media dimensions where practical to reduce layout shift, and lazy-load non-critical media when it does not hide required content.
- Prefer system or intentionally loaded font stacks; font loading must not make core content unreadable.
- Avoid unnecessary client rendering for static content when server/static delivery better satisfies the product requirement.

## Metadata and SEO

When discoverability or link presentation is a product requirement:

- provide meaningful page titles and descriptions;
- use canonical and social metadata according to the product's publishing contract;
- preserve crawlable semantic content where indexing is required;
- ensure route-specific metadata follows route-specific content; and
- do not treat client-only visual rendering as sufficient evidence of search visibility.

For private tools where SEO is irrelevant, do not add SEO infrastructure merely because it is common in public websites.

## Browser security boundary

- Treat URL parameters, storage, postMessage data, third-party content, pasted markup, and network responses as untrusted input.
- Never render unsanitized untrusted HTML. `dangerouslySetInnerHTML` requires an explicit trusted/sanitized source boundary and reviewable justification.
- Do not place secrets in frontend bundles, source maps, local storage, public environment variables, or client-visible configuration.
- Prefer secure server-managed authentication/session boundaries. Client-side guards are presentation behavior, not authorization.
- Use `rel="noopener noreferrer"` or equivalent safe behavior when opening untrusted external destinations in a new browsing context where applicable.
- Content Security Policy, trusted types, cross-origin policy, and related controls should follow the deployment/security architecture when that architecture owns them; do not fabricate deployment policy inside a component.

## User-visible and offline states

Extend the shared deterministic-state contract with web-specific behavior:

- loading states must preserve orientation and avoid trapping focus;
- empty states must distinguish valid zero-data outcomes from missing evidence or failed retrieval;
- errors must remain visible and actionable without replacing the last known valid state with fabricated success;
- offline or interrupted-network states must be explicit when the application can encounter them;
- disabled controls must communicate why the action is unavailable when that reason is needed to proceed; and
- stale responses must not overwrite newer route, form, or query state.

Do not add service workers, offline persistence, optimistic writes, or retry loops unless the product contract requires them.

## Testing and browser acceptance

Web validation should be layered according to risk:

1. **Pure logic tests** for shared domain rules and validation projections.
2. **Component tests** for user-visible states, forms, accessible names, keyboard interactions, and bounded browser behavior.
3. **Browser end-to-end tests** for representative critical journeys, routing/history behavior, dialogs/focus, and integration seams that component tests cannot prove.
4. **Responsive acceptance** at representative narrow, medium, and wide viewport classes selected from product requirements rather than device-brand snapshots.
5. **Accessibility acceptance** combining automated checks with keyboard/focus/semantic behavioral coverage.

Browser tests must avoid production credentials and external writes unless separately governed. Prefer privacy-safe fixtures and deterministic local/test adapters.

Visual snapshots may support regression detection, but they do not replace semantic, interaction, responsive, or accessibility assertions. Avoid brittle full-page pixel assertions when a smaller behavioral or bounded visual invariant proves the requirement.

## Web versus shared/native decision rule

Share domain logic, validated types/projections, state machines, API clients where platform-safe, and design-token meaning when reuse is real. Keep implementation platform-specific when the browser's semantics are part of correctness.

A web-only component is preferred when sharing would require suppressing semantic HTML, native browser behavior, CSS capability, metadata, accessibility, or performance. A shared component is preferred when behavior and semantics remain equivalent across targets without platform conditionals dominating the implementation.

Document a material platform split when it affects architecture; do not pursue a percentage code-sharing target.

## Non-goals

This standard does not:

- require Next.js, Vite, React Native Web, a CSS framework, or a component library globally;
- create a Web Agent or generic frontend framework;
- build or deploy a production website;
- redefine canonical backend schemas in TypeScript;
- authorize credentials, hosting, deployment, analytics, production, or external writes; or
- replace the shared TypeScript + React standard.
