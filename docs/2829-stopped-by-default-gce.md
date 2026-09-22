# #2829 — Stopped-by-default GCE lifecycle

## Purpose

Agent OS keeps `agent-os-test` available for concrete VM-specific capabilities
without treating idle uptime as a requirement. Ordinary developer-loop work keeps
the #2299 Codespaces-first preference. GCE remains the bounded fallback for the
#2300 capability boundary and for current host-local authenticated browser capture.

## Developer validation lifecycle

The existing fixed GCE developer-validation transport now consumes the same
resource lifecycle instead of requiring a pre-running host:

```text
accepted fixed validation request
-> observe exact agent-os-test state
-> START only when STOPPED
-> wait for RUNNING
-> execute the fixed validation profile
-> require terminal success/failure + cleanup_complete
-> STOP only when the existing adapter's shutdown capability is enabled
-> independently observe STOPPED
```

A RUNNING host is never redundantly started. Transitional or unknown host state
fails closed. Start failure, cleanup failure, timeout, malformed evidence, stop
failure, or failed provider-state verification never becomes successful lifecycle
evidence.

The generic governed Scheduler control path continues to use #1241's stricter
termination + lease-release + cleanup + quarantine shutdown eligibility. #2829
does not weaken or duplicate that gate.

## Browser-session boundary

Stopping the VM is lifecycle actuation only. It does not delete, export, copy,
recreate, or authorize access to Adobe, Canva, Schoology, or other host-local
browser profile contents. Manual authentication and the existing fixed-session
capture contracts remain unchanged. A separately admitted browser operation may
require GCE to be running; that requirement is resolved before its execution, not
by keeping the VM permanently running.

## Authorization boundary

Repository code and synthetic tests do not authorize a live VM start or stop.
Live activation requires fresh current consumer/lease/browser-session evidence and
the separately governed Cloud mutation authorization. No IAM, WIF, OS Login,
firewall, network, workflow, protected-setting, credential, or billing change is
introduced here.

## Live canary

After repository implementation is merged/current and a live lifecycle operation
is separately authorized, use one genuine admitted GCE-required operation:

```text
fresh preflight
-> provider state STOPPED
-> bounded START
-> fixed operation
-> terminal cleanup evidence
-> evidence-gated STOP
-> provider readback STOPPED
```

Do not manufacture a production workload solely to prove this sequence.
