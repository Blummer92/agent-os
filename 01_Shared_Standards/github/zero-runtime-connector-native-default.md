# Zero-Runtime Connector-Native Default

## Invariant
For an already-authorized repository operation, when the canonical capability classification requires no checkout, process execution, tests, build, lint, dependency installation, runtime inspection, generated-artifact inspection, or other runtime capability, and the connected GitHub surface supports the exact operation, route through the GitHub connector/API by default.

```text
required runtime capabilities = empty
+ connector supports exact operation
-> connector-native GitHub route
```

Do not invoke the governed runner, Execution VM, Cloud Build, local `git`, or local `gh` solely because those routes exist.

## Reuse boundary
This standard consumes #918 executor/capability classification, #1330 connector-native fast-track behavior, #1237 same-lineage reroute semantics, Safe Implementation Lane authorization/currentness, and GitHub Service Agent write ownership. It creates no second router, writer, Scheduler, retry system, or validation authority.

## Zero-runtime examples
Documentation/policy edits with a zero-command validation profile, bounded issue/PR metadata operations, connector-supported branch/file creation or exact whole-file replacement, and other repository mutations whose canonical validation plan requires zero runtime commands.

## Runtime-required exclusion
Python/TypeScript/JavaScript changes requiring tests, lint/build/compile work, dependency-sensitive changes, generated artifacts, runtime inspection, package/build validation, local Git reconciliation, or issue-required executable commands remain on the governed runtime path.

## Continuation
A zero-runtime operation remains connector-native across continuation/retry while capability evidence remains sufficient. If the connector becomes insufficient, preserve the same authorized lineage and consume #1237/#918 reroute semantics. Do not silently escalate or falsely complete.

## Currentness
Before every mutation, reacquire exact repository, branch/head, target/blob, authorization, and scope currentness required by the existing mutation contract. Stale head/blob evidence fails closed and is reacquired; it does not justify a runtime route.

## Compute avoidance
A genuinely zero-runtime route does not require VM health, dependency readiness, local CLI availability, or Cloud Build availability merely to perform the mutation. Required final validation remains governed by the existing testing/release policy.

## Authority
GitHub Service Agent remains the sole repository writer. This routing default grants no merge, closure, protected-setting, workflow, credential, production, or external-write authority.
