# Canva Browser Bootstrap Operator Runbook

Issue: #2455
Related PPUX evidence owner: #2108
Tinkercad precedent: #2450 / PR #2453

## Purpose

This runbook documents the later, separately authorized operator procedure for establishing or refreshing Canva authentication on the existing governed GCE host:

```text
project = agent-os-502614
zone = us-central1-a
instance = agent-os-test
browser_session_ref = canva-default
```

Repository implementation alone does not authorize host mutation, package installation, IAP/SSH use, browser launch, Canva login, capture execution, or Canva content writes.

Canva uses a dedicated Linux capture identity and host-local profile. Do not share or copy Adobe, Tinkercad, or Canva browser profiles, cookies, tokens, passwords, MFA material, or SSO artifacts.

## Fixed architecture

```text
human operator
-> existing bounded IAP / OS Login access
-> fixed root-owned Canva bootstrap on agent-os-test
-> dedicated agent-os-canva-capture identity
-> transient Xvfb display :99
-> Chromium with fixed Canva profile
-> x11vnc loopback port 5903
-> websockify/noVNC loopback port 6082
-> SSH local forwarding over the existing IAP-backed SSH path
-> manual Canva / SSO / MFA interaction
-> browser close or 30-minute TTL
-> deterministic teardown
-> Canva profile remains host-local
```

No arbitrary URL/profile input, public listener, generic desktop launcher, remote-debugging/CDP transport, password automation, profile transfer, or authentication assertion is introduced.

## Repository artifacts

- `scripts/agent-os-canva-browser-session` — fixed unprivileged Canva session; accepts no arguments.
- `scripts/install-canva-browser-bootstrap` — separately authorized root installer; accepts no arguments.
- `/usr/local/libexec/agent-os-canva-browser-bootstrap` — fixed outer entrypoint created only during authorized activation.
- `/usr/local/libexec/agent-os-canva-browser-session` — fixed root-owned inner entrypoint executed as the dedicated Canva capture identity.

## Separately authorized activation

Every action below mutates or operates the live host and therefore requires explicit owner authorization after exact-head review/merge.

1. Verify the exact reviewed/merged source, fixed target tuple, existing IAP/OS Login access, and Debian 12 host. Do not widen IAM, WIF, firewall, workflow, or credential scope.
2. From the exact reviewed checkout, an authorized administrator invokes only `08_Tooling/agent-os-execution-service/scripts/install-canva-browser-bootstrap`.
3. Start only `sudo /usr/local/libexec/agent-os-canva-browser-bootstrap`.
4. Preserve the loopback boundary. Because noVNC listens on VM localhost, use SSH local forwarding over IAP rather than opening a firewall port:

```text
gcloud compute ssh agent-os-test \
  --project=agent-os-502614 \
  --zone=us-central1-a \
  --tunnel-through-iap \
  --ssh-flag="-4" \
  --ssh-flag="-N" \
  --ssh-flag="-L 127.0.0.1:6082:127.0.0.1:6082" \
  --ssh-flag="-o ExitOnForwardFailure=yes"
```

5. Open `/vnc.html?autoconnect=1&resize=scale` through local port `6082` (Cloud Shell Web Preview may be used when Cloud Shell owns the local forward).
6. Perform Canva / SSO / MFA login manually in the visible Chromium session. Do not automate password entry, automate MFA, bypass SSO, inspect/extract/print/copy cookies or tokens, copy the profile off-host, or place auth material in GitHub/logs/prompts.
7. During live qualification, test the landing page, authenticated dashboard, create/open design, basic text/image editing, and one presentation/design workflow. Graphics-heavy/video/animation behavior is a separate qualification dimension; do not infer failure from Tinkercad's WebGL result.
8. Close Chromium when manual qualification is complete. Otherwise the fixed 30-minute TTL terminates the session.
9. Retain only the opaque identity `browser_session_ref = canva-default` for downstream use. Bootstrap lifecycle output never asserts `AUTH_READY`; authentication readiness requires a separately governed downstream probe/capture contract.

## Product isolation

Adobe and Tinkercad remain unchanged at their existing identities/profiles/displays/ports. Canva uses a different capture user, home/profile, X display, VNC port, and noVNC port. Do not migrate or reuse profile state between products.

## Rollback

Repository rollback is an ordinary Git revert of the #2455 implementation. Live-host rollback is separately authorized: stop an active Canva session and remove fixed installed entrypoints/packages only when safe. Never silently destroy the persistent Canva profile/authentication state as part of repository rollback.
