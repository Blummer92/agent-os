# Cloud Build / Scheduler Lease Lifecycle

Issue #1211 composes the existing Cloud Build provider lifecycle with the existing Workflow Scheduler lease lifecycle. It creates neither a second Scheduler nor a Cloud-specific lease system.

## Invariant
Once remote submission may have occurred, Scheduler ownership is retained until provider evidence proves terminal execution and the existing teardown/release contract permits release.

- working/nonterminal provider evidence -> retain lease;
- ambiguous submission or observation -> bounded reconciliation of the same invocation; never blind resubmit;
- exactly one reconciliation match -> resume observation of that same build;
- zero/multiple matches -> unknown/manual review; retain lease;
- polling/network failure -> not proof of termination;
- unsupported/denied cancellation -> not proof of termination;
- terminal validation result -> validation evidence only; lease release still follows existing proven-terminal teardown rules.

Bind repository, issue/handoff, execution/invocation, branch/source/tested SHA, provider invocation/build identity, selected provider/executor, and Scheduler lease holder/generation through their existing canonical identities.

No GitHub mutation, Cloud activation, IAM/credential change, workflow mutation, automatic retry, force release, persistent remote workspace, queue, database, daemon, webhook, merge, or issue closure is authorized by this composition contract.
