# Ephemeral GCE/IAP Software-Tutorial Capture Ingress

Issue #2491 adds the smallest bounded transport needed to move one already-validated Recorder payload from an authorized caller to the existing software-tutorial capture worker on the fixed Agent OS GCE host.

## Scope

This contract is intentionally **not** an `ExecutorHandoff` / `RuntimeExecutionRequest` extension. Those objects reconstruct repository/Scheduler execution around `SingleIssuePilotInput`; authentic Recorder bytes and a browser replay workload are a different payload class. Reusing their unrelated fields would weaken source-of-truth and compatibility boundaries.

The fixed Canva live-capture flow is:

```text
software-tutorial-capture-request-v1
-> runGceLiveCaptureWithEvidence(...)
-> existing runLiveCaptureRequest validation
-> invokeGceCapture(...)
-> gcloud compute ssh over IAP to agent-os-test
-> fixed sudo command only
-> /usr/local/libexec/agent-os-canva-software-tutorial-capture
-> dedicated agent-os-canva-capture identity
-> stdin-only Recorder envelope
-> live_capture_host.mjs
-> exact Recorder SHA-256 re-verification
-> existing captureFlow(...)
-> /dev/shm screenshot workspace
-> bounded capture + screenshot bytes on stdout
-> deterministic tmpfs cleanup
-> Picture Perfect evidence binding
```

## Fixed execution surface

```text
project  = agent-os-502614
zone     = us-central1-a
instance = agent-os-test
```

`gce_capture_transport.mjs` builds the entire `gcloud compute ssh` argv from repository-owned constants. It sets `shell: false`, accepts no caller-provided executable, SSH command, shell text, port, display, profile path, launch arguments, or alternate resource tuple, and selects only fixed session-owned host entrypoints.

For Canva the remote command is exactly:

```text
sudo -n /usr/local/libexec/agent-os-canva-software-tutorial-capture
```

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
- resolves the browser profile only from repository-owned host configuration.

The host contract knows the existing bootstrap identities:

| browser session | required host user | fixed profile |
|---|---|---|
| `adobe-express-default` | `agent-os-capture` | `/var/lib/agent-os/capture-home/.agent-os/browser-profiles/adobe-express` |
| `canva-default` | `agent-os-canva-capture` | `/var/lib/agent-os/canva-capture-home/.agent-os/browser-profiles/canva` |
| `schoology-default` | `agent-os-schoology-capture` | `/var/lib/agent-os/schoology-capture-home/.agent-os/browser-profiles/schoology-kami` |

The stdin request never carries those filesystem paths or user identities. If the process is not running as the exact session owner, the host returns a bounded `browser-session-user-mismatch` blocker and performs zero Replay calls.

## Ephemeral evidence

Authentic Recorder data and screenshots are sensitive by default and are not a new durable Agent OS store.

For one admitted capture, the host creates a private workspace under:

```text
/dev/shm/agent-os-software-tutorial-capture-*/
```

`captureFlow(...)` writes its normal BEFORE/AFTER PNG files only inside that tmpfs workspace. The host then reads the bounded PNG set into the response, sets `evidence_persisted=false`, and deletes the entire workspace in `finally` on both success and failure.

`invokeGceCapture(...)` accepts a maximum of 256 screenshot records and caps transport stdout at 128 MiB. The ordinary `runGceLiveCaptureRequest(...)` API remains receipt-only for backward compatibility. `runGceLiveCaptureWithEvidence(...)` is the explicit sensitive-evidence API: it returns screenshot bytes only when the capture itself is `valid`. Partial screenshots from a blocked replay are not promoted into approved evidence.

No screenshot or authentic Recorder is committed to Git, posted to a GitHub issue, placed in an Actions artifact, written to GCS/Drive, or retained in a new host capture directory by this path.

## Replay

The host delegates to the existing #932 `captureFlow(...)` implementation with:

- the exact validated Recorder bytes;
- exact approved origins;
- the existing capture-request identity;
- the fixed host-local browser profile;
- the ephemeral tmpfs screenshot directory;
- current `AUTH_READY` evidence;
- system Chromium at `/usr/bin/chromium`;
- target-style capture disabled by default, preserving the current v1 output contract.

Transport success remains distinct from capture success. A returned screenshot is still sensitive capture evidence; Picture Perfect must validate its capture/provenance binding before any portable prompt becomes Ready.

## Authentication

No password, SSO credential, MFA value, cookie, token, profile bytes, or browser-profile path crosses the transport boundary. Authentication remains manual and host-local under the existing Adobe/Canva bootstrap contracts. `AUTH_READY` is capability evidence; it is not publication authority.

If the live Canva profile is no longer authenticated, the end-to-end mission stops for the human operator to refresh Canva/SSO/MFA through the existing governed browser bootstrap. Login automation is not added here.

## Fixed host runtime

Repository files:

- `scripts/agent-os-canva-software-tutorial-capture` — root-owned no-argv outer entrypoint;
- `scripts/agent-os-canva-software-tutorial-capture-session` — no-argv unprivileged session entrypoint;
- `scripts/install-canva-software-tutorial-capture` — bounded root installer for the reviewed capture package/runtime.

The installer is a live-host mutation and is **not executed by repository implementation**. After merge, activation remains governed by the current end-to-end owner authorization and must fail closed if its exact privilege/runtime assumptions are not current.

The installer:

- requires the existing `agent-os-canva-capture` identity and fixed Canva profile;
- pins Node `22.16.0` and verifies the official Linux x64 archive SHA-256 before installation;
- installs only the reviewed capture package under `/opt/agent-os/software-tutorial-capture`;
- uses the host's existing `/usr/bin/chromium` and suppresses Puppeteer's browser download;
- installs the two fixed no-argv entrypoints;
- creates one exact sudo rule for existing transport principal `sa_117278680011452280250` to invoke only `/usr/local/libexec/agent-os-canva-software-tutorial-capture` as root;
- validates candidate and global sudoers with `visudo`;
- does not grant a shell, Python, arbitrary executable, wildcard command, second principal, profile access path, IAM/WIF, firewall, or network authority.

A need to broaden that privilege contract, add another principal, change IAM/WIF/OS Login/firewall/network policy, or expose a generic file-transfer/command surface is a stop condition rather than an implicit extension of this design.

## Schoology/Kami fixed route (#2809)

The Schoology/Kami capture route reuses the same fixed GCE/IAP transport and existing capture worker with no generic browser selector. `schoology-default` maps only to:

```text
sudo -n /usr/local/libexec/agent-os-schoology-software-tutorial-capture
```

The session request origin set is exactly `https://dpscd.schoology.com` plus `https://web.kamihq.com`. The dedicated browser bootstrap uses a host-local Schoology/Kami profile; no password, MFA value, SSO artifact, cookie, token, profile path, or profile bytes cross the capture request/result boundary. Repository implementation does not install or start this route on the live VM.

The first live use is separately gated by #2812 and must begin in a teacher-owned sandbox/test course with no student data. It must establish manual Schoology authentication first and reach Kami through the normal LTI launch; a need for independent Kami credential automation is a stop condition.

Repository files for the Schoology/Kami runtime are the fixed no-argv outer/session entrypoints plus `install-schoology-software-tutorial-capture`. The installer copies the reviewed capture package, including `file_input_bindings.mjs`, and grants the existing transport principal sudo only for the one fixed Schoology capture entrypoint.

## Tutorial 0 empirical target

After this repository slice is reviewed/merged and the fixed host runtime is current, the first empirical target is the authentic project artifact `tutorial 0 - canva.json`:

```text
exact Recorder bytes
-> SHA-256 verification before transport
-> canva-default / AUTH_READY
-> fixed GCE/IAP stdin transport
-> host SHA-256 re-verification
-> existing captureFlow
-> BEFORE/AFTER screenshots + selector/geometry evidence
-> direct ephemeral evidence return
-> Picture Perfect capture binding
-> Canva image prompts
```

The operator should not manually SCP the Recorder, choose SSH commands, select a profile path, start Node manually, or click through the recorded tutorial solely to produce capture evidence.

## Repository validation

Run from `08_Tooling/instructional-materials-coach/capture/`:

```bash
npm test
npm run check
```

The exact-head validation profile also runs `npm ci` before those checks. Repository tests are synthetic and credential-free; they inject process/capture boundaries rather than touching GCE, IAP, Chromium accounts, or authentic Recorder data.

## Rollback

Repository rollback is an ordinary revert of the #2491 implementation. Live-host rollback, if activation has later occurred, is separately governed and should remove only the fixed capture entrypoints/runtime/sudo fragment while preserving the existing Canva profile unless the owner separately authorizes profile removal.
