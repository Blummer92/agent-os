# Tinkercad Browser Bootstrap Operator Runbook

Issue: #2450
Graphics investigation: #2456
Related PPUX evidence owner: #2108
Adobe precedent: #2106

## Purpose

This runbook documents the later, separately authorized operator procedure for establishing or refreshing Tinkercad authentication on the existing governed GCE host:

```text
project = agent-os-502614
zone = us-central1-a
instance = agent-os-test
browser_session_ref = tinkercad-default
```

Repository implementation alone does not authorize host mutation, package installation, IAP/SSH use, browser launch, Tinkercad login, or capture execution.

Tinkercad uses a dedicated Linux capture identity and host-local profile. Do not share or copy Adobe/Tinkercad browser profiles, cookies, tokens, passwords, MFA material, or SSO artifacts.

## Fixed architecture

```text
human operator
-> existing bounded IAP / OS Login access
-> fixed root-owned Tinkercad bootstrap on agent-os-test
-> dedicated agent-os-tinkercad-capture identity
-> transient Xvfb display :98
-> Chromium with fixed Tinkercad profile
-> x11vnc loopback port 5902
-> websockify/noVNC loopback port 6081
-> SSH local forwarding over the existing IAP-backed SSH path
-> manual Tinkercad / Autodesk / SSO / MFA interaction
-> browser close or 30-minute TTL
-> deterministic teardown
-> Tinkercad profile remains host-local
```

No arbitrary URL/profile input, public listener, generic desktop launcher, remote-debugging/CDP transport, password automation, profile transfer, or authentication assertion is introduced.

## #2456 WebGL investigation disposition

Live evidence for #2456 shows the current Debian 12/Xvfb session reaches the authenticated Tinkercad dashboard but the 3D editor does not initialize. The same evidence records `/dev/dri` absent, Mesa llvmpipe, and Chromium reporting WebGL, WebGL2, OpenGL, and GPU compositing disabled after GPU-process instability.

The repository session intentionally does **not** add a software-WebGL override. Current Chromium treats SwiftShader fallback for WebGL as a security-sensitive compatibility path rather than an ordinary supported acceleration mode; forcing it would weaken the existing #2456 boundary against browser-security bypass. In particular, do not add `--enable-unsafe-swiftshader`, `--ignore-gpu-blocklist`, `--disable-gpu-sandbox`, remote-debugging/CDP flags, or equivalent force-enable switches to this governed browser bootstrap without a separately reviewed compatibility/security decision.

Therefore the bounded repository disposition is:

```text
SOFTWARE_WEBGL_PATH_NOT_ADMISSIBLE_UNDER_CURRENT_SECURITY_CONTRACT
```

This does not claim that software rasterization is technically impossible. It records that the available force-enable route is outside this issue's authorized security envelope. The next architecture step, if Tinkercad 3D remains required, is a separately governed graphics-host decision that can provide supported WebGL2/hardware acceleration while preserving the dedicated profile, loopback-only viewer, manual-auth, no-secret, TTL, and cleanup invariants. No GPU purchase, VM resize, or cloud mutation is authorized by this repository change.

## Repository artifacts

- `scripts/agent-os-tinkercad-browser-session` — fixed unprivileged Tinkercad session; accepts no arguments.
- `scripts/install-tinkercad-browser-bootstrap` — separately authorized root installer; accepts no arguments.
- `/usr/local/libexec/agent-os-tinkercad-browser-bootstrap` — fixed outer entrypoint created only during authorized activation.
- `/usr/local/libexec/agent-os-tinkercad-browser-session` — fixed root-owned inner entrypoint executed as the dedicated Tinkercad capture identity.

## Separately authorized activation

Every action below mutates or operates the live host and therefore requires explicit owner authorization after exact-head review/merge.

1. Verify the exact reviewed/merged source, fixed target tuple, existing IAP/OS Login access, and Debian 12 host. Do not widen IAM, WIF, firewall, workflow, or credential scope.
2. From the exact reviewed checkout, an authorized administrator invokes only `08_Tooling/agent-os-execution-service/scripts/install-tinkercad-browser-bootstrap`.
3. Start only `sudo /usr/local/libexec/agent-os-tinkercad-browser-bootstrap`.
4. Preserve the loopback boundary. Because noVNC listens on VM localhost, use SSH local forwarding over IAP rather than opening a firewall port. A Cloud Shell example is:

```text
gcloud compute ssh agent-os-test \
  --project=agent-os-502614 \
  --zone=us-central1-a \
  --tunnel-through-iap \
  --ssh-flag="-4" \
  --ssh-flag="-N" \
  --ssh-flag="-L 127.0.0.1:6081:127.0.0.1:6081" \
  --ssh-flag="-o ExitOnForwardFailure=yes"
```

5. Open the operator viewer through the local forwarded port: `/vnc.html?autoconnect=1&resize=scale` on local port `6081` (Cloud Shell Web Preview may be used when Cloud Shell owns the local forward).
6. Perform Tinkercad / Autodesk / SSO / MFA login manually in the visible Chromium session. Do not automate password entry, automate MFA, bypass SSO, inspect/extract/print/copy cookies or tokens, copy the profile off-host, or place auth material in GitHub/logs/prompts.
7. Close Chromium when manual login/inspection is complete. Otherwise the fixed 30-minute TTL terminates the session.
8. Retain only the opaque identity `browser_session_ref = tinkercad-default` for downstream use. Bootstrap lifecycle output never asserts `AUTH_READY`; authentication readiness requires a separately governed downstream probe/capture contract.

## Adobe isolation

Adobe remains unchanged at its existing identity/profile/display/ports. Tinkercad uses a different capture user, home/profile, X display, VNC port, and noVNC port. Do not migrate or reuse Adobe profile state for Tinkercad.

## Rollback

Repository rollback is an ordinary Git revert of the #2450/#2456 documentation change. Live-host rollback is separately authorized: stop an active Tinkercad session and remove fixed installed entrypoints/packages only when safe. Never silently destroy the persistent Tinkercad profile/authentication state as part of repository rollback.
