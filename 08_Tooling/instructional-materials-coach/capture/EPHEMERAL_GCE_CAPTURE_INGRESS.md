# Ephemeral GCE/IAP Software-Tutorial Capture Ingress

Issue #2491 adds the smallest bounded transport needed to move one already-validated Recorder payload from an authorized caller to the existing software-tutorial capture worker on the fixed Agent OS GCE host.

## Scope

This contract is intentionally **not** an `ExecutorHandoff` / `RuntimeExecutionRequest` extension. Those objects reconstruct repository/Scheduler execution around `SingleIssuePilotInput`; authentic Recorder bytes and a browser replay workload are a different payload class. Reusing their unrelated fields would weaken source-of-truth and compatibility boundaries.

The fixed live-capture flow is:

```text
software-tutorial-capture-request-v1
-> runLiveCaptureRequest(...)
-> invokeGceCapture(...)
-> gcloud compute ssh over IAP to agent-os-test
-> stdin-only Recorder envelope
-> fixed /usr/local/libexec/agent-os-software-tutorial-capture
-> live_capture_host.mjs
-> exact Recorder SHA-256 re-verification
-> existing captureFlow(...)
-> bounded transport/capture result
```

## Fixed execution surface

```text
project  = agent-os-502614
zone     = us-central1-a
instance = agent-os-test
```

`gce_capture_transport.mjs` builds the entire `gcloud compute ssh` argv from repository-owned constants. It sets `shell: false`, accepts no caller-provided executable, SSH command, shell text, port, display, profile path, launch arguments, or alternate resource tuple, and uses only the fixed host entrypoint.

The authentic Recorder is serialized only to the child process's stdin. The transport creates no Recorder file, cache, queue, registry, database, object-store object, GitHub artifact, issue attachment, or other durable input copy.

## Host boundary

`live_capture_host.mjs` accepts no CLI arguments. Its stdin schema is closed and must contain exactly the bounded fields emitted by `runLiveCaptureRequest(...)`.

Before Replay it:

- re-verifies the fixed GCE execution-surface identity;
- requires `operation = captureFlow`;
- requires a governed browser-session identity;
- requires `AUTH_READY`;
- requires `privacy_mode = sensitive-by-default`;
- re-hashes the authentic Recorder bytes and requires an exact SHA-256 match;
- rejects unknown fields and oversized input;
- resolves browser profile and screenshot locations only from repository-owned host configuration.

The host contract currently knows the existing bootstrap identities:

| browser session | required host user | fixed profile |
|---|---|---|
| `adobe-express-default` | `agent-os-capture` | `/var/lib/agent-os/capture-home/.agent-os/browser-profiles/adobe-express` |
| `canva-default` | `agent-os-canva-capture` | `/var/lib/agent-os/canva-capture-home/.agent-os/browser-profiles/canva` |

The stdin request never carries those filesystem paths or user identities. If the process is not running as the exact session owner, the host returns a bounded `browser-session-user-mismatch` blocker and performs zero Replay calls.

## Replay and outputs

The host delegates to the existing #932 `captureFlow(...)` implementation with:

- the exact validated Recorder bytes;
- exact approved origins;
- the existing capture-request identity;
- the fixed host-local browser profile;
- a capture-request-specific host-local screenshot directory;
- current `AUTH_READY` evidence;
- system Chromium at `/usr/bin/chromium`;
- headless replay after authentication has already been established manually;
- target-style capture disabled by default, preserving the current v1 output contract.

Screenshots remain sensitive host-local capture evidence. This ingress does not upload screenshots to GitHub or make them publication-ready.

## Authentication

No password, SSO credential, MFA value, cookie, token, profile bytes, or browser-profile path crosses the transport boundary. Authentication remains manual and host-local under the existing Adobe/Canva bootstrap contracts. `AUTH_READY` is capability evidence; it is not execution, publication, or external-write authority.

## Runtime installation / privilege boundary

Repository implementation alone does not publish `/usr/local/libexec/agent-os-software-tutorial-capture` or install Node dependencies on `agent-os-test`.

The installed host entrypoint must remain a fixed no-argv wrapper over the reviewed capture package and must execute as the exact dedicated browser-session owner. Any host-runtime publication or local privilege/delegation required to run that wrapper is a live-host mutation and must use its separately authorized bounded installation path. Do not replace this requirement with generic sudo, generic SSH commands, a public upload service, profile ACL widening, or profile copying.

## Input and result limits

The transport and host independently cap stdin at 512 KiB. Transport stdout is capped at 2 MiB. Capture result identity remains bounded by `runLiveCaptureRequest(...)`; successful transport does not imply successful capture.

## Tutorial 0 empirical target

After this repository slice is reviewed/merged and the fixed host runtime is current, the first empirical target is `tutorial 0 - canva.json`:

```text
exact Recorder bytes
-> SHA-256 verification
-> canva-default / AUTH_READY
-> fixed GCE/IAP stdin transport
-> existing captureFlow
-> BEFORE/AFTER screenshots + selector/geometry evidence
-> Picture Perfect evidence binding
```

Manual Canva re-authentication remains the only interactive browser step. The operator should not manually SCP the Recorder, choose SSH commands, select a profile path, start Node manually, or click through the recorded tutorial solely to produce capture evidence.

## Repository validation

Run from `08_Tooling/instructional-materials-coach/capture/`:

```bash
npm test
npm run check
```

Repository tests are synthetic and credential-free. They inject the process boundary and capture implementation rather than touching GCE, IAP, Chromium accounts, or authentic Recorder data.

## Rollback

Revert `gce_capture_transport.mjs`, `live_capture_host.mjs`, their tests, package check update, and this document. Repository rollback does not delete authenticated browser profiles, host-local captures, Scheduler state, credentials, IAM/WIF, firewall rules, or other external state.
