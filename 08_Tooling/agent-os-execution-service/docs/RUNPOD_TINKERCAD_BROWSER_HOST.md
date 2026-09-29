# #2787 — Runpod Community Tinkercad browser host

## Purpose

This repository contract defines the fixed GPU-backed successor to the rejected GCE/Xvfb/software-rendering Tinkercad path. Repository implementation does not create a Pod, API key, network volume, billing resource, or live browser session.

## Fixed target

- provider: Runpod
- cloud: Community Cloud
- first qualification GPU: NVIDIA RTX A5000
- maximum per-Pod session: 7200 seconds
- browser: Chromium
- display: GPU-backed Xorg/X11 display supplied by the fixed runtime image
- viewer: x11vnc/noVNC on loopback only
- operator transport: SSH local forwarding only
- authentication: manual Autodesk/Tinkercad/SSO/MFA
- browser profile: fresh ephemeral profile deleted at teardown

The runtime must fail closed if the fixed GPU or GPU-backed display is unavailable. It must not fall back to the old Xvfb-only/llvmpipe path.

## Security boundary

No CDP or remote-debugging port is permitted. Do not use unsafe SwiftShader, GPU-blocklist bypass, disabled GPU sandbox, disabled web security, public VNC/noVNC, automated login, cookie/token export, or a persisted authenticated browser profile.

Network or persistent storage, if a later separately authorized live Pod uses it, is restricted to non-secret runtime assets/configuration. It must not contain cookies, tokens, the browser profile, or authentication state.

## Operator connection

The Pod exposes no public viewer. The operator uses the provider's bounded SSH access and forwards the fixed loopback noVNC port:

```text
operator 127.0.0.1:6081
  -> SSH local forward
  -> Pod 127.0.0.1:6081
  -> loopback x11vnc
  -> GPU-backed display :0
  -> Chromium
```

Provider credentials and the exact live SSH command remain outside repository source and are acquired only during separately authorized #2788 qualification.

## Lifecycle and cleanup

The provider launch contract must also set a stop-after bound of no more than two hours. The in-Pod session independently enforces the same 7200-second bound. Browser close, timeout, signal, component failure, or GPU loss tears down Chromium/viewer processes and deletes the ephemeral profile.

A stopped Community Pod may lose its GPU slot. Replacement is a fresh Pod with a fresh authentication profile; do not persist auth state merely to survive provider replacement.

## #2788 handoff

#2788 remains blocked until this repository implementation is exact-head validated and separately authorized paid provider execution exists. That qualification must prove the exact GPU, hardware-backed WebGL2/OpenGL, Tinkercad workplane rendering, one create/move interaction, manual-auth boundaries, private viewer, teardown, and actual billed cost.

## Rollback

Repository rollback removes this Runpod-specific contract/session and tests. No provider rollback is implied because #2787 performs no provider mutation.
