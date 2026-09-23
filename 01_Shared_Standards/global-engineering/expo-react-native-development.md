# Expo + React Native Development Standard

## Scope

This standard extends `typescript-react-development.md` for iOS and Android application work using Expo + React Native. Expo + React Native is the preferred Agent OS mobile path when it satisfies product requirements; evidence may justify another native stack when required capabilities cannot be met safely through the Expo-supported path.

This standard does not create a Mobile Agent, authorize app publication or credentials, or redefine canonical backend contracts in TypeScript.

## Expo project and workflow boundary

- Prefer the current supported Expo workflow and Expo-supported libraries when they satisfy requirements.
- Keep application code, shared domain logic, platform adapters, assets, tests, and configuration separated by responsibility rather than by arbitrary screen size.
- Treat Expo configuration as application configuration, not a secret store. Values embedded in a client application are client-visible unless a separately governed backend boundary protects them.
- Do not add custom native projects, config plugins, native modules, or prebuild/eject-style complexity solely for convenience. Require a concrete capability gap and document the resulting native maintenance boundary.
- Keep development, preview/test, and production configuration distinguishable. Never use production credentials merely to exercise a reference or test path.

## React Native components and styling

- Use React Native primitives according to native interaction semantics rather than reproducing browser markup patterns mechanically.
- Keep styling explicit, composable, and bounded. Prefer shared design-token meaning while allowing platform-specific implementation where native behavior differs.
- Derive display state instead of synchronizing duplicate state, consistent with the shared React standard.
- Keep platform/device effects behind bounded adapters so domain logic remains deterministic and testable.
- Use platform-specific files or branches only when behavior genuinely differs; do not fork components merely because both platforms exist.

## Platform-safe TypeScript and shared logic

Prioritize sharing:

- domain models and validated projections;
- pure business and validation logic;
- deterministic state machines/state transitions;
- API clients when their transport/storage assumptions are platform-safe;
- design-token meaning; and
- presentational components only when semantics and interaction remain equivalent.

Do not assume browser globals, Node-only APIs, filesystem paths, DOM types, or web storage exist in native code. Keep platform adapters explicit at those boundaries.

Do not pursue 100% code sharing. Shared code is valuable only when it preserves correctness and maintainability.

## Navigation and deep links

- Use one intentional navigation model with typed/bounded route parameters where practical.
- Define back behavior, initial route, invalid/deep-link handling, and restoration behavior for important flows.
- Deep-link inputs are untrusted. Validate route parameters before using them as domain or authorization evidence.
- Navigation visibility is not authorization. Server/provider boundaries remain authoritative for protected operations.
- Avoid hidden parallel navigation state that can disagree with the navigation system's canonical route state.

## Safe area, keyboard, orientation, and screen size

- Respect platform safe areas for content and interactive controls where system UI can overlap the application.
- Keyboard appearance must not make required controls unreachable. Forms should remain usable with the on-screen keyboard open.
- Layouts must tolerate representative phone and tablet dimensions and expected text scaling rather than relying on one device's pixel dimensions.
- Support orientation changes when the product permits them; otherwise make an intentional supported-orientation decision in application configuration.
- Prefer flexible layout primitives and measured content behavior over hard-coded device models.

## Accessibility and touch targets

Accessibility is implementation acceptance, not polish.

- Give interactive controls meaningful accessibility roles, names/labels, states, and hints when the native semantics do not provide enough context.
- Preserve logical screen-reader traversal and focus behavior.
- Interactive targets must be large and separated enough for ordinary touch use; use the applicable platform/accessibility target guidance rather than tiny visual hit areas.
- Do not communicate required state by color alone.
- Respect user text-size and accessibility settings where the product can reasonably support them.
- Motion, haptics, and animation must not be the sole carrier of required meaning; respect reduced-motion preferences when applicable.
- Test representative flows with accessibility-oriented queries/semantics rather than only implementation IDs.

## Permissions and least privilege

- Request a native permission only when the user reaches a feature that needs it, unless the platform requires a different timing contract.
- Explain the user-facing reason when context is not obvious.
- Request the narrowest permission/capability that satisfies the feature.
- Permission denial, restricted status, unavailable hardware, and permanently denied/settings-required states are normal deterministic states, not exceptional crashes.
- Do not repeatedly prompt after denial without a product-defined recovery path.
- Permission status in the UI does not grant backend authority.

## Device API boundary

Camera, photo library, file/document access, location, contacts, notifications, sensors, and similar capabilities must sit behind explicit adapters.

- Prefer Expo-supported APIs when they satisfy requirements.
- Validate and normalize provider/device results before domain use.
- Treat media metadata, file names, URIs, deep-link payloads, and external content as untrusted input.
- Make capability-unavailable behavior explicit for simulators, unsupported devices, policy restrictions, and missing hardware.
- Reference fixtures and ordinary tests must use mock/test seams rather than real personal media, location, accounts, or device permissions.

A native module or custom native implementation requires evidence that the Expo-supported path cannot meet the requirement and should be treated as a higher-complexity architecture decision.

## Storage and secrets

Classify data before choosing persistence.

- Ordinary non-sensitive preferences/cache may use an appropriate local persistence mechanism.
- Authentication tokens, private keys, or similarly sensitive small secrets require an approved secure-storage mechanism appropriate to the platform and threat model.
- Do not put secrets in AsyncStorage-equivalent ordinary persistence, source code, app configuration, logs, fixtures, analytics payloads, or client-visible environment variables.
- Device secure storage is not a substitute for server-side authorization or secret management.
- Define logout/account-removal cleanup for sensitive local state when the product stores it.

## Network, offline, and retry behavior

- Model connectivity failure and request failure separately when the distinction affects recovery.
- Preserve last-known valid data only when the product contract permits it, and label stale/offline state truthfully.
- Do not fabricate success from a queued, cached, or locally optimistic action.
- Retries must be bounded and safe for the operation. Never blindly retry a non-idempotent external mutation.
- Background synchronization, persistent offline queues, and conflict resolution require explicit product requirements; do not add them as default mobile infrastructure.

## Required user-visible states

Mobile features must define applicable deterministic states including:

- loading;
- empty;
- success;
- error;
- offline/interrupted network;
- permission not requested;
- permission denied/restricted;
- settings-required when recovery needs system settings; and
- device capability unavailable.

State transitions must not hide failed or stale evidence. A permission or capability failure must not render as a generic empty-success state.

## iOS and Android differences

- Treat platform differences as explicit product behavior when they affect permissions, navigation/back behavior, safe areas, keyboards, storage, share/file providers, background execution, notifications, or lifecycle.
- Prefer a shared implementation when semantics remain equivalent.
- Use `Platform` checks or platform-specific modules/files when behavior genuinely differs and keep the divergence as narrow as practical.
- Do not make one platform's observed behavior the undocumented default for the other.
- Validate important flows on representative iOS and Android targets before claiming cross-platform acceptance.

## Lifecycle and background behavior

- Assume the operating system may pause, terminate, or recreate the application. Do not rely on in-memory state as durable evidence.
- Handle foreground/background transitions only when the feature needs them.
- Background tasks, location, audio, uploads, notifications, and similar execution have platform policy, battery, permission, and scheduling constraints; introduce them only for explicit requirements.
- Never imply guaranteed continuous background execution when the platform does not provide it.
- Reacquire stale data or authorization after lifecycle transitions when the governing backend contract requires currentness.

## Performance

- Measure before adding memoization or architecture complexity.
- Use list virtualization for materially large collections rather than rendering unbounded item sets.
- Keep render-item work bounded and use stable identity for list items.
- Size/process media appropriately and avoid retaining large unnecessary objects in component state.
- Avoid JS-thread-heavy work in interaction-critical paths; move expensive work behind an appropriate bounded capability when measurement proves the need.
- Performance optimization must not weaken accessibility, correctness, or state truthfulness.

## Expo configuration and environment handling

- Keep app identifiers, supported orientations, deep-link schemes, permissions declarations, and platform configuration intentional and reviewable.
- Client environment variables/configuration are not secret merely because they are injected at build time.
- Signing credentials, certificates, provisioning profiles, store credentials, production service credentials, and deployment secrets are outside this standard's implementation authority.
- Configuration changes that alter production permissions, native capabilities, signing, deployment, or store behavior require their separately governed authorization.

## Testing and device acceptance

Use layered validation according to risk:

1. **Pure unit tests** for shared domain logic, validation, and state transitions.
2. **Component tests** for native-visible states, accessibility semantics, form behavior, and mocked device/permission adapters.
3. **Integration tests** for navigation, persistence/network adapters, and platform seams where isolated component tests are insufficient.
4. **Device/simulator end-to-end acceptance** for representative critical journeys when the product risk justifies it.
5. **Cross-platform acceptance** on representative iOS and Android targets for behavior claimed to be shared.
6. **Layout acceptance** across representative phone and tablet dimensions when tablet support is claimed.

Tests must not require production credentials, personal accounts, real user media/location, app-store publication, or external writes unless separately authorized.

Mocks must preserve meaningful failure states: permission denied, unavailable capability, offline/error responses, and platform divergence should be testable rather than collapsed into success fixtures.

## Upgrade and dependency policy

- Prefer Expo-compatible dependency versions and the supported compatibility matrix for the selected Expo SDK.
- Upgrade Expo/React Native and native-facing dependencies deliberately, reviewing platform behavior and migration notes rather than independently bumping tightly coupled packages.
- Add a native-facing dependency only for a concrete capability gap and prefer maintained Expo-supported paths when equivalent.
- Treat major Expo SDK/React Native upgrades as compatibility changes requiring representative iOS/Android validation.
- Do not freeze one repository-wide Expo SDK version in this standard; project constraints and current supported releases determine the bounded version choice.

## React Native Web boundary

React Native Web is an option, not a mandate.

Use it when the interface is application-like and the shared component's semantics, accessibility, interaction, and layout remain appropriate on the browser.

Prefer React DOM/HTML/CSS when semantic document structure, native browser forms/links/tables, browser APIs, metadata/SEO, CSS capabilities, or web-specific accessibility make the web implementation materially clearer or more correct. `react-web-development.md` owns that browser-specific guidance.

Do not force the semantic web fixture or public document-style interfaces through React Native Web merely to increase code sharing.

## Non-goals

This standard does not:

- build or publish an application;
- create Apple or Google developer accounts;
- configure signing credentials, certificates, provisioning, store records, or production deployment;
- require React Native Web for web work;
- create a Mobile Agent or generic mobile framework;
- redefine canonical backend schemas in TypeScript;
- authorize production or external writes; or
- guarantee that Expo can satisfy a requirement that demonstrably needs custom native code.
