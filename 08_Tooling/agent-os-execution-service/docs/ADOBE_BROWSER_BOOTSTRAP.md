# Adobe Browser Bootstrap Operator Runbook

Issue: #2106
Parent decision: #2099
Sibling capture-request lane: #2100
Empirical Adobe capture owner: #932

## Purpose

This runbook documents the **later, separately authorized** operator procedure for establishing or refreshing Adobe Express authentication on the existing governed GCE host:

```text
project = agent-os-502614
zone = us-central1-a
instance = agent-os-test
browser_session_ref = adobe-express-default
```

Repository implementation alone does not authorize any host mutation, package installation, IAP/SSH use, browser launch, Adobe login, or capture execution.

The browser profile remains host-local at all times. Do not copy browser profiles, cookies, tokens, passwords, MFA material, or SSO artifacts to GitHub, Notion, Drive, workflow artifacts, another machine, or ordinary logs.

## Architecture boundary

The bootstrap is intentionally narrow:

```text
human operator
-> existing bounded IAP / OS Login access
-> fixed root-owned bootstrap entrypoint on agent-os-test
-> dedicated unprivileged capture identity
-> transient Xvfb display
-> Chromium with one fixed host-local Adobe profile
-> transient x11vnc bound to loopback only
-> transient websockify/noVNC bound to loopback only
-> operator IAP TCP tunnel
-> manual Adobe / SSO / MFA interaction
-> operator closes Chromium or bounded TTL expires
-> deterministic process teardown
-> browser profile remains on agent-os-test
```

No public listener, persistent VNC daemon, generic remote-desktop service, Chrome remote-debugging/CDP port, arbitrary shell/argv transport, browser-profile transfer, or authentication automation is introduced.

## Repository artifacts

- `scripts/agent-os-adobe-browser-session` — fixed unprivileged browser/display session. Accepts no arguments.
- `scripts/install-adobe-browser-bootstrap` — separately authorized root installer. Accepts no arguments and installs fixed root-owned entrypoints plus the dedicated capture identity/profile directory.
- `/usr/local/libexec/agent-os-adobe-browser-bootstrap` — fixed outer host entrypoint created by the installer.
- `/usr/local/libexec/agent-os-adobe-browser-session` — fixed root-owned inner entrypoint executed as `agent-os-capture`.

The repository does not publish or run these artifacts on the live host automatically.

## Separately authorized activation procedure

Every step in this section is a live-host/external operation and requires explicit owner authorization after exact-head repository review.

### 1. Verify the reviewed source and host prerequisites

Confirm all of the following before touching the host:

- the reviewed PR head SHA is the exact source being used;
- the target tuple is exactly `agent-os-502614 / us-central1-a / agent-os-test`;
- existing bounded IAP / OS Login access is already available;
- no IAM, WIF, firewall, public-ingress, workflow, or credential expansion is required;
- the host remains the qualified Debian 12 execution surface.

If any prerequisite is false, stop. Do not broaden permissions or create a substitute host inside this procedure.

### 2. Install the fixed bootstrap artifacts

From the exact reviewed checkout on the qualified host, an authorized administrator may invoke only:

```text
08_Tooling/agent-os-execution-service/scripts/install-adobe-browser-bootstrap
```

The installer has no caller-selected command, path, URL, profile, display, port, or arbitrary argv input. It installs the required browser/display packages, the dedicated `agent-os-capture` identity, one fixed host-local profile directory, and root-owned fixed entrypoints.

Installation is a live-host mutation. Do not run it under ordinary repository implementation authority.

### 3. Start the fixed browser bootstrap

On the qualified host, an authorized operator invokes only:

```text
sudo /usr/local/libexec/agent-os-adobe-browser-bootstrap
```

The session emits bounded lifecycle evidence and exposes no terminal, file manager, or general desktop through the viewer.

Bootstrap output never asserts `AUTH_READY`. A completed operator session means only that the human-visible session ended.

### 4. Create the IAP TCP tunnel

On the operator workstation, use the existing authorized Google identity and fixed target tuple to tunnel only the noVNC loopback port:

```text
gcloud compute start-iap-tunnel agent-os-test 6080 \
  --local-host-port=127.0.0.1:6080 \
  --zone=us-central1-a \
  --project=agent-os-502614
```

Do not add a public firewall rule or bind the viewer to a non-loopback interface.

### 5. Open the local browser-view URL

Open only:

```text
http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale
```

The underlying x11vnc and websockify listeners are loopback-only on the host. The viewer is an ephemeral browser-only surface, not a standing remote-desktop service.

### 6. Perform Adobe login manually

Use the visible Chromium session to complete Adobe / SSO / MFA manually.

Hard rules:

- do not automate password entry;
- do not automate MFA;
- do not bypass SSO;
- do not inspect, extract, print, or copy cookies/tokens;
- do not copy the profile directory off-host;
- do not record login steps in Chrome Recorder;
- do not paste authentication material into GitHub comments, logs, prompts, or handoff packets.

### 7. End the operator session

Close Chromium when login is complete. If the browser is not closed, the fixed 30-minute TTL ends the session.

The bootstrap tears down Chromium, websockify, x11vnc, Xvfb, and the temporary Xauthority file on normal close, timeout, signal, or component failure. The persistent browser profile is intentionally preserved.

### 8. Retain the host-local profile only

The canonical opaque identity is:

```text
browser_session_ref = adobe-express-default
```

Downstream callers use only that identity. They must never receive the filesystem profile path or profile bytes.

### 9. Let #932 probe authentication later

After bootstrap teardown, the existing #932 capture worker is responsible for probing the Adobe session and producing one of its canonical auth states:

```text
AUTH_READY
AUTH_REQUIRED
AUTH_EXPIRED
AUTH_BLOCKED
```

Only #932 may determine `AUTH_READY`. Bootstrap completion does not imply authentication success.

## Explicit non-goals

This bootstrap does not:

- execute Recorder JSON;
- capture screenshots;
- invoke Puppeteer replay;
- invoke Scheduler jobs;
- invoke a provider;
- publish tutorial assets;
- write to Drive or Notion;
- make classroom changes;
- mutate IAM/WIF/firewall/workflow settings;
- create a public endpoint;
- expose Chrome CDP/remote debugging;
- create a generic crawler or Browser Agent.

## Rollback

Rollback of the repository change is the ordinary Git revert of the #2106 implementation commit/PR.

Rollback of a separately authorized host activation is a separate administrator action: stop any active bootstrap session, remove the fixed installed entrypoints and optional browser/display packages if no longer needed, and remove the dedicated capture account/profile only if the owner explicitly authorizes destroying that authentication state. Never silently delete the browser profile as part of ordinary repository rollback.
