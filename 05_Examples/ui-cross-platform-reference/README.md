# Cross-platform React / Expo reference fixture

This is executable teaching evidence for `typescript-react-development.md`, `react-web-development.md`, and `expo-react-native-development.md`. It is deliberately small and is not a production application, starter framework, design system, or dependency for Agent OS runtime code.

## What is shared

`shared/task.ts` owns the typed task projection, pure title validation, deterministic loading/empty/success/error states, and a repository interface. Those rules have no DOM, React Native, browser-storage, device, credential, or production dependency.

## What stays web-specific

`web/TaskPanel.tsx` uses semantic HTML, native form controls, ARIA only where needed, keyboard-operable buttons, an accessible dialog, explicit focus restoration, and responsive CSS. The semantic web implementation is intentionally not routed through React Native Web.

`tests/web.e2e.ts` is the browser-level acceptance example. It proves semantic role discovery, form validation, keyboard dialog operation, Escape dismissal, and focus restoration against the Vite-served fixture.

## What stays native-specific

`mobile/TaskScreen.tsx` uses React Native primitives, safe-area layout, a phone/tablet width boundary, accessibility roles/labels, 44-point minimum interaction targets, a bounded screen transition, and an injected device-capability interface.

The capability seam is mocked in `tests/mobile.test.tsx`; tests do not request a real permission, read personal media, use credentials, contact an external API, or perform an external write. Denied and unavailable capability outcomes remain explicit user-visible states.

## Why rendering is not shared

The domain contract is genuinely portable, but the browser needs semantic HTML/CSS/focus behavior while native needs React Native accessibility, safe-area, touch-target, and device-capability behavior. Sharing those renderers would make the example less correct merely to increase code-sharing percentage.

## Running the fixture tests

From this directory in a disposable development/test environment:

```text
npm install
npm test
npx playwright install chromium
npm run test:web
```

The package is private and has no publish/deploy script. Do not supply production credentials or real device permissions.

## Remote validation coverage (#3184)

The Agent OS remote-validation selector owns this fixture as the
`ui-cross-platform-reference` focused rule. A change to any fixture-owned path —
including a dependency-only `package.json` change such as a Vitest version bump —
selects exactly these affected-package commands, in order:

```text
cd 05_Examples/ui-cross-platform-reference && npm install
cd 05_Examples/ui-cross-platform-reference && npm test
```

`npm install` re-resolves the fixture's declared dependencies (the package is
private and carries no lockfile, so `npm install` is the supported install step
rather than `npm ci`), and `npm test` runs the vitest unit suite
(`tests/shared.test.ts`, `tests/web.test.tsx`, `tests/mobile.test.tsx`) on the
Node/npm/vitest toolchain declared in `package.json`. The Playwright acceptance
path (`npm run test:web`) is teaching evidence for the browser layer and is not
part of the dependency-change coverage. The remote route executes both commands
at the change's exact head SHA and returns the bounded stdout/stderr and exit
status as validation evidence bound to that head SHA — the same exact-head
evidence contract every focused validation plan carries.

## Demonstrated states

- shared: loading, empty, success, error;
- web: empty, validation error, dialog open/closed and keyboard focus path;
- native: empty/error-compatible rendering, bounded screen transition, permission granted/denied/unavailable seam;
- network/provider failure: the shared repository adapter returns an explicit error state rather than fabricated success.
