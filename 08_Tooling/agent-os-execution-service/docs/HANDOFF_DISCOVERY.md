# Governed Handoff Discovery — #1237

## Purpose

#1237 adds one read-only locator at the existing #1218 checkpoint-owned invocation-descriptor boundary. It solves only the bootstrap problem where a trusted integration knows the canonical repository and issue but does not yet possess the immutable `executor-handoff:<sha256>` identity.

```text
repository + issue
-> scan existing bounded #1218 invocation-descriptor store
-> validate every descriptor read
-> exactly one matching descriptor => existing immutable handoff id
-> zero matches => not-found
-> multiple matches / corruption / unavailable store => needs-decision
-> existing #1218 reconstruction/current-evidence/lease checks
-> Scheduler admission or fail closed
```

## Authority boundary

Discovery is not authorization and is not currentness. The result has all authority and side-effect fields fixed false. A found handoff must still pass `reconstruct_governed_invocation(...)`, including current route, authorization, source/scope, checkpoint, ResumePlan, environment/dependency, workspace/runtime, and Scheduler lease checks.

The locator never:

- creates or persists a handoff, route decision, checkpoint, or descriptor;
- chooses among multiple historical descriptors;
- interprets issue prose, chat text, labels, or branch names as execution authority;
- acquires/releases a lease or invokes the Scheduler;
- performs GitHub, network, subprocess, cloud, VM lifecycle, credential, merge, issue-closure, or external writes;
- adds a second index, database, queue, daemon, retry system, router, Scheduler, or authority store.

## Store behavior

The implementation scans only `<store_root>/invocations/*.json`, the existing bounded #1218 descriptor directory. The existing maximum descriptor count remains the scan bound. Each candidate is deserialized canonically and its filename is checked against its immutable handoff identity. Store unavailability, any descriptor-integrity failure, or a descriptor count above the existing bound returns `needs-decision` without exposing a handoff.

Repository matching is case-insensitive; issue matching is exact. The locator does not use file timestamps, directory order, `latest` heuristics, or issue status to select a candidate.

Multiple descriptors for the same repository and issue are intentionally ambiguous at this seam. The locator does not guess which historical handoff is current; currentness remains downstream canonical evidence and must be resolved explicitly rather than inferred from descriptor age.

## Integration handoff

A ChatGPT-side or host-side integration may use this locator only as the read step that obtains an existing handoff identity. It must preserve the established route precedence and then invoke the existing bounded `/agent-os resume executor-handoff:<sha256>` transport. If no unique handoff exists, the integration must not synthesize one or silently fall back to local CLI.

The first landed consumer is the Claude Code execution-interface preflight: `.claude/settings.json` wires `UserPromptSubmit` and `PreToolUse` hooks to `scripts/agent-os-execution-interface-preflight.py`, which runs before generic GitHub publish tooling checks local `git`/`gh`. It calls this locator and reports the resulting existing ingress, adding no routing, authorization, descriptor, or execution authority of its own.

The GitHub/GCE consumer added by #1284 uses the existing bounded GCE adapter to invoke the tracked `agent_os_execution_service.handoff_discovery_entrypoint` Python module directly with only canonical repository + positive issue identity. Readiness is a fixed module-import probe. Both the probe and module invocation are pinned to the qualified Debian system interpreter `/usr/bin/python3`; OS Login or caller `PATH` cannot select a different Python runtime. The adapter does not require or install a second `/usr/local/libexec/agent-os-handoff-discovery` executable and exposes no generic remote-command surface. The module still consumes the existing #1242 locator and host-composed checkpoint-store binding; discovery remains non-authorizing and never invokes Scheduler.

The same `/usr/bin/python3` interpreter is used by the hardened #1238 host-runtime installer and by the installed governed-resume wrapper. Installation therefore proves imports in the interpreter that discovery and resume subsequently execute, instead of allowing root and OS Login PATH resolution to diverge.

The only canonical installed Agent OS GCE execution entrypoint remains `/usr/local/libexec/agent-os-governed-resume`, owned by #1238. A discovered handoff must traverse that existing resume/currentness/Scheduler path before execution. #1239 remains the owner of live GitHub-to-GCE invocation and replay qualification.

## Rollback

Remove the locator consumer binding and its focused tests, or revert the locator module itself if #1237 is rolled back. No second discovery executable exists to uninstall. The existing #1218 descriptor format/store, immutable handoff identities, reconstruction, Scheduler state, `/usr/local/libexec/agent-os-governed-resume`, GCE transport, branches, PRs, and external resources remain unchanged.
