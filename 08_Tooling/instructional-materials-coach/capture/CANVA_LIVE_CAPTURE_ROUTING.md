# Canva governed live-capture routing

Issue: #2489

## Purpose

Route the already-governed Canva browser session into the existing #932/#2100 live tutorial capture seam without creating another replay engine or generic browser executor.

The admitted Canva identity is fixed:

```text
browser_session_ref = canva-default
origin              = https://www.canva.com
execution surface   = gce-iap / agent-os-502614 / us-central1-a / agent-os-test
privacy mode        = sensitive-by-default
```

Adobe Express remains admitted through the existing `adobe-express-default` identity with its pre-#2489 exact-HTTPS request semantics unchanged.

## Boundary

`runLiveCaptureRequest(...)` still delegates execution to the existing `captureFlow` transport. The request layer does not implement Recorder parsing, Puppeteer Replay, screenshot capture, selector resolution, target geometry, browser launch, authentication, or profile handling.

Only the exact governed browser-session allowlist is accepted. Canva requests are additionally bound to `https://www.canva.com`; a `canva-default` request paired with another target/allowed origin fails closed before transport invocation. Adobe keeps the existing request-origin behavior for backward compatibility. Unknown session identities fail closed.

The request schema remains closed. Callers cannot add profile paths, display identifiers, ports, executable paths, launch arguments, shell commands, scripts, passwords, cookies, tokens, MFA/SSO material, or other browser instructions.

Authentication remains manual. `AUTH_READY` is required before replay; `AUTH_REQUIRED`, `AUTH_EXPIRED`, and `AUTH_BLOCKED` remain blocked states.

The execution surface remains fixed to `agent-os-test` through GCE/IAP. There is no local, Cloud Build, provider, alternate-host, or public-listener fallback.

## Evidence and privacy

Successful transport may return only the existing bounded capture receipt/evidence identity. Real Recorder content and screenshots remain sensitive-by-default and must not be committed to GitHub.

Transport success does not imply Picture Perfect readiness, classroom readiness, publication authority, or external-write authority.

## Tutorial 0 empirical target

After separately authorized live execution, `tutorial 0 - canva.json` is the first empirical target:

```text
Recorder JSON
-> governed request validation
-> canva-default authenticated browser session
-> existing captureFlow / Puppeteer Replay worker
-> BEFORE/AFTER screenshots + selector/geometry evidence
-> bounded capture receipt
-> Picture Perfect prompt generation
```

Repository implementation does not itself authorize live-host activation or replay.
