# Modeled Software Tutorial Capture Spike

Repository-only Phase 1 implementation for Agent OS issue #932 (parent #931).
This package validates Chrome DevTools Recorder JSON before execution and provides
one thin Puppeteer Replay capture shell for later controlled Adobe Express proof.

## Boundary

This directory is capture/replay evidence only. It does not implement tutorial
wording, Teacher Modeling binding, `software-tutorial-v1`, PPTX rendering, Drive
publication, Notion writes, AI grouping, OCR, computer vision, or UI repair.
The live Adobe Express spike is a manual/controlled contract test and is not run
by ordinary CI.

## Runtime

- Node `>=22.12 <23`
- `@puppeteer/replay` `4.0.2`
- `puppeteer` `25.3.0`

Install from this directory with `npm ci`. The package is isolated from root
Node dependencies. Tests use only Node's built-in `node:test`.

## Safety preflight

`validateRecording(rawRecording, { approvedOrigins })` hashes the original bytes
first, then parses and validates the recording. It accepts only the Recorder step
types authorized by #932:

`setViewport`, `navigate`, `click`, `doubleClick`, `change`, `hover`, `scroll`,
`keyDown`, `keyUp`, and `waitForElement`.

It rejects `waitForExpression`, `customStep`, `emulateNetworkConditions`, `close`,
and every unknown future type. Navigation requires an exact caller-supplied HTTPS
origin such as `https://new.express.adobe.com`. Sensitive key names and email-like
values route to `manual-review-required`; raw captures are sensitive by default.

Reason codes use existing Agent OS-compatible prefixes (`artifact-*`, `quality-*`,
`asset-*`, and `authority-*`) and finite capture states from #932.

## Replay capture

`captureFlow(...)` always runs preflight before importing a recording into Replay.
It requires an explicit dedicated `userDataDir` outside the repository. The
recommended operator location is:

`~/.agent-os/browser-profiles/adobe-express/`

Authentication is manual only. A controlled operator preflight supplies one exact
status: `AUTH_READY`, `AUTH_REQUIRED`, `AUTH_EXPIRED`, or `AUTH_BLOCKED`.
`captureFlow(...)` launches Replay only for `AUTH_READY`; the other statuses fail
closed with the matching finite `authority-auth-*` reason. This package does not
auto-detect login state, record login, automate passwords/MFA/SSO, extract
cookies/tokens, or commit a browser profile.

The capture extension records viewport screenshots before and after each step and
bounded selector/geometry observations where Puppeteer can inspect a simple
selector. Capture JSON stores screenshot filenames rather than absolute local
paths. Replay remains the authoritative executor for the Recorder selector
alternatives.

No real unsanitized screenshot or Recorder capture belongs in Git. Repository
fixtures must remain synthetic or sanitized and human-reviewed.

## Local checks

```bash
npm test
npm run check
```

A later authorized live spike must perform the repeated Adobe runs and return the
GO/MODIFY/STOP measurement packet required by #932. This repository package alone
cannot produce that verdict.
