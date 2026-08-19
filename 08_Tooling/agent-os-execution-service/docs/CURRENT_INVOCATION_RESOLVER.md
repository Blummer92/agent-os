# Current Invocation Resolver — #1218

`current_invocation_resolver.py` completes the repository-local composition boundary left after the original #1218 descriptor/reconstruction seam and #1226 execution-authorization source.

The resolver accepts one verified `GovernedInvocationDescriptor`, asks injected existing owners to read or rebuild the current route, handoff, checkpoint, ResumePlan, candidate packet, runtime configuration, dependency readiness, and pilot input, and reacquires current execution authorization through #1226. It then returns `CurrentInvocationEvidence` to the existing `reconstruct_governed_invocation(...)` cross-checker.

The module deliberately owns no GitHub client, candidate store, runtime store, route store, authorization store, Scheduler lifecycle, lease mutation, retry, provider selection, subprocess, or cloud operation. `SingleIssuePilotInput` remains an in-memory composition and is never persisted by this seam.

`persist_current_invocation_descriptor(...)` is the bounded writer for the point where a governed-runner handoff is already runnable. It writes only the existing descriptor's reference identities through `append_invocation_descriptor(...)`; complete authorization, route, checkpoint, candidate, dependency, runtime, and pilot objects remain with their canonical owners.

The intended host flow remains:

```text
immutable handoff id
-> load checkpoint-owned descriptor
-> CanonicalCurrentInvocationResolver
-> #1226 current authorization + existing current evidence owners
-> existing reconstruct_governed_invocation cross-checks
-> existing #758/#1202 lease observation
-> existing Scheduler input
```

Failure to reacquire a required current evidence family is fail-closed. The resolver never treats descriptor history, transport authentication, workflow state, comment prose, or cloud identity as execution authority.

Rollback is repository-only: revert this resolver, its tests, and this note. No external or persistent runtime migration is performed.