# Schoology/Kami Browser Bootstrap Operator Runbook

Issue: #2809
Empirical validation successor: #2812
Capture architecture: #931 / #932 / #2100 / #2491

## Purpose

This runbook documents the later, separately authorized operator procedure for establishing or refreshing Schoology authentication on the existing governed GCE host while keeping the normal Schoology -> Kami LTI flow in one dedicated host-local browser profile.

```text
project = agent-os-502614
zone = us-central1-a
instance = agent-os-test
browser_session_ref = schoology-default
Schoology origin = https://dpscd.schoology.com
Kami origin = https://web.kamihq.com
```

Repository implementation alone does not authorize host mutation, package installation, IAP/SSH use, browser launch, Schoology/Kami login, classroom access, capture execution, assignment changes, grading, or other Schoology/Kami writes.

## Fixed architecture

```text
human operator
-> existing bounded IAP / OS Login access
-> fixed root-owned Schoology bootstrap on agent-os-test
-> dedicated agent-os-schoology-capture identity
-> transient Xvfb display :100
-> Chromium with fixed schoology-kami profile
-> x11vnc loopback port 5904
-> websockify/noVNC loopback port 6083
-> SSH local forwarding over the existing IAP-backed SSH path
-> manual Schoology / district SSO / MFA interaction
-> normal Schoology LTI launch into Kami
-> browser close or 30-minute TTL
-> deterministic teardown
-> profile remains host-local
```

No arbitrary URL/profile input, public listener, generic desktop launcher, remote-debugging/CDP transport, password automation, MFA automation, SSO bypass, cookie/token extraction, or profile transfer is introduced.

## Repository artifacts

- `scripts/agent-os-schoology-browser-session` — fixed unprivileged Schoology/Kami operator session; accepts no arguments.
- `scripts/install-schoology-browser-bootstrap` — separately authorized root installer; accepts no arguments.
- `scripts/agent-os-schoology-software-tutorial-capture` — fixed root-owned capture entrypoint; accepts no arguments and stdin only.
- `scripts/agent-os-schoology-software-tutorial-capture-session` — fixed unprivileged capture session.
- `scripts/install-schoology-software-tutorial-capture` — separately authorized fixed capture-runtime installer.

## Separately authorized activation

Every action below mutates or operates the live host and requires explicit current owner authorization after the exact reviewed implementation is merged/current.

1. Reacquire the exact reviewed source, fixed GCE tuple, host state, and current authorization.
2. An authorized administrator invokes only `install-schoology-browser-bootstrap`; installing the capture runtime is a separate live-host activation action.
3. Start only `sudo /usr/local/libexec/agent-os-schoology-browser-bootstrap`.
4. Preserve loopback-only viewer access. Use the existing IAP-backed SSH path to forward local port `6083`; do not open a firewall listener.
5. Open the noVNC view through the local forward.
6. Authenticate manually to Schoology and any district SSO/MFA challenge. Never automate or extract credentials, cookies, tokens, MFA values, or SSO state.
7. Use a teacher-owned sandbox/test course only. Do not open real student submissions, gradebook rows, messages, or other student data for the first qualification.
8. Launch Kami through the normal Schoology LTI path. Do not create a separate Kami login flow unless #2812 proves LTI continuity insufficient and a new governed decision explicitly authorizes a different approach.
9. Close Chromium when qualification is complete; otherwise the fixed 30-minute TTL terminates the operator session.
10. Retain only `browser_session_ref = schoology-default`. Bootstrap lifecycle output never asserts `AUTH_READY`; the downstream capture host independently probes current auth before Replay.

## Capture routing

A Schoology live-capture request must use the exact fixed origins:

```text
https://dpscd.schoology.com
https://web.kamihq.com
```

The capture route accepts neither wildcard tenants nor caller-selected Kami origins. It resolves only to the fixed Schoology host entrypoint and dedicated profile. Raw Recorder data and screenshots remain sensitive-by-default and ephemeral under the existing capture contract.

## Product isolation

Schoology/Kami uses a different capture user, home/profile, X display, VNC port, and noVNC port from Adobe Express, Tinkercad, and Canva. Never migrate or reuse profile/authentication state between these products.

## Rollback

Repository rollback is an ordinary revert of the #2809 implementation. Live-host rollback, if activation is later authorized and performed, removes only the fixed Schoology bootstrap/capture entrypoints and runtime-specific sudo fragment when safe. Do not silently destroy the persistent Schoology/Kami profile or authentication state.
