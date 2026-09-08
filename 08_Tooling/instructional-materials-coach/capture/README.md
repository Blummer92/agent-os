# Modeled Software Tutorial Capture Spike

Repository-only Phase 1 implementation for #932 (parent #931). This package validates Chrome DevTools Recorder JSON before execution, provides a thin Puppeteer Replay capture shell, owns the RJ3 Recorder-conformance adapter from #1125, and owns the RJ4 synthetic replay-equivalence harness from #1126.

## Boundary

This directory is capture/replay evidence only. It does not own tutorial wording, Teacher Modeling binding, `software-tutorial-v1`, rendering, Drive/Notion writes, AI grouping, OCR, computer vision, UI repair, instructional approval, or live-application fidelity claims. Live Adobe testing remains a manual/controlled contract test outside ordinary CI.

## Runtime

- Node `>=22.12 <23`
- `@puppeteer/replay` `4.0.2`
- `puppeteer` `25.3.0`

Run `npm ci` here. The package is isolated from root Node dependencies and tests use Node's built-in `node:test`.

## Safety preflight

`validateRecording(rawRecording, { approvedOrigins })` hashes source bytes first, then applies #932's execution preflight. Allowed step types are `setViewport`, `navigate`, `click`, `doubleClick`, `change`, `hover`, `scroll`, `keyDown`, `keyUp`, and `waitForElement`.

It rejects `waitForExpression`, `customStep`, `emulateNetworkConditions`, `close`, and unknown future types. Navigation requires an exact caller-supplied HTTPS origin. Sensitive values route to `manual-review-required`; raw captures are sensitive by default. Reason codes use existing `artifact-*`, `quality-*`, `asset-*`, and `authority-*` families.

## Recorder conformance (RJ3 / #1125)

`validateRecorderConformance(rawRecording)` is the canonical Recorder-format gate. It fingerprints exact input bytes, separates JSON syntax failure from Recorder rejection, then delegates format parsing to pinned `@puppeteer/replay` `4.0.2`.

Statuses are `json-invalid`, `recorder-invalid`, `recorder-valid`, `validator-unavailable`, and `validator-error`. Every result records input SHA-256, validator name/version, parse status, bounded diagnostic codes, and `behavioral_equivalence_proven: false`. Raw upstream exception text and local paths are never returned.

### Dependency upgrades

Replay is exact-pinned in `package.json` and `package-lock.json`, and the adapter verifies the installed version equals `4.0.2`. Mismatch fails closed as `validator-error`. Any upgrade requires explicit dependency review and the full RJ3 positive/negative compatibility matrix before changing the supported version.

## Replay equivalence (RJ4 / #1126)

`validateReplayEquivalence(originalRaw, candidateRaw)` runs only against the local synthetic `rj4-app.html` fixture. Candidate replay is blocked unless RJ3 returns `recorder-valid`. The harness resets state between runs, compares normalized observable checkpoints and final state rather than step count or selector identity, and returns only `equivalent`, `not-equivalent`, `indeterminate`, or `runner-unavailable` for the behavioral comparison.

Evidence binds original/candidate SHA-256 digests, fixture version/digest, exact Replay version, normalized checkpoints/final state, and bounded failure reasons. `indeterminate` and `runner-unavailable` are fail-closed and never imply rewrite safety. Every result keeps `external_write_authorized=false` and `production_authorized=false`.

The synthetic fixture includes folder/card actions, title changes, click/double-click distinction, modal behavior, recoverable error/recovery, bounded delayed state, stable and fragile-looking selectors, ordering-sensitive actions, and duplicate/noise cases. Tests cover all twelve required #1126 fixture-pair classes plus a real headless pinned-Replay smoke path.

The browser harness blocks requests except `about:blank` and the in-memory fixture document. It performs no Adobe, Schoology, PowerSchool, Notion, Drive, classroom, account, provider, or production access.

## Recorder testing ladder

`JSON syntax -> Recorder conformance (RJ3) -> semantic/provenance invariants (RJ1/RJ2) -> deterministic replay equivalence (RJ4) -> separately authorized application-specific empirical fidelity`

RJ3 proves only Recorder-format compatibility. RJ4 proves only behavioral equivalence inside the bounded synthetic fixture. Neither proves instructional correctness, current Adobe UI fidelity, source authenticity, or production safety.

## Replay capture

`captureFlow(...)` always runs preflight before Replay. It requires a dedicated `userDataDir` outside the repository; recommended location: `~/.agent-os/browser-profiles/adobe-express/`.

Authentication is manual only. Operator status is exactly `AUTH_READY`, `AUTH_REQUIRED`, `AUTH_EXPIRED`, or `AUTH_BLOCKED`; only `AUTH_READY` may launch Replay. No password/MFA/SSO automation, cookie/token extraction, or committed browser profile is allowed.

The capture extension records bounded selector/geometry evidence and viewport screenshots before/after each step. Capture JSON stores screenshot filenames, not absolute paths. Replay remains authoritative for execution.

No real unsanitized screenshot or Recorder capture belongs in Git. Repository fixtures must remain synthetic or sanitized and human-reviewed.

### Capture format v2 / optional target-style evidence (#1485)

`captureFlow({ ..., captureTargetStyle: true })` opts into `software-tutorial-capture-v2`, which adds one optional bounded `target_style` snapshot per resolved action from a frozen `getComputedStyle` property allowlist on the already-resolved target handle only (no DOM traversal). Colors persist as canonical RGBA; `background_image` retains bounded CSS gradients and blocks `url(...)`/`blob:`/`data:` resource identity. Style resolution failure leaves `target_style: null` rather than blocking or fabricating a value, since Replay stays authoritative for execution regardless.

`captureTargetStyle` defaults to `false`, which keeps `format_version: software-tutorial-capture-v1` and its existing shape byte-identical. Adding `target_style` never changes `fingerprintAction()` output or recording identity.

## Local checks

```bash
npm test
npm run check
```

A later separately authorized live spike must produce #932's GO/MODIFY/STOP packet. This repository package alone cannot produce that verdict.
