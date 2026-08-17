# Governed Invocation Binding — #1203

`governed_invocation_binding.py` is the repository-local seam between the already-merged GitHub issue-comment ingress and the already-merged #1217 GCE control-path contract.

It accepts only an `IssueCommentIngressResult` whose transport status is `accepted`, reason is `accepted-envelope`, run attempt is exactly `1`, and whose immutable handoff/logical-trigger identities are present. It binds that evidence to one exact `GceResourceTuple` and derives one deterministic `gce-control-request:<sha256>` identity.

The binding grants no execution, Scheduler, cloud, GitHub-write, retry, or arbitrary-command authority. It performs no GCP, GitHub, credential, network, subprocess, Scheduler, lease, persistence, VM-start/stop, or provider action.

The production sequence is intentionally split:

```text
/agent-os resume <executor-handoff-id>
-> #1203 issue-comment ingress
-> GovernedInvocationBinding
-> separately authorized #1217 OIDC/WIF + GCE control adapter
-> fixed /usr/local/libexec/agent-os-governed-resume --handoff-id <id>
-> #1218 descriptor + CanonicalCurrentInvocationResolver
-> reconstruct_governed_invocation(...)
-> #758/#1202 lease truth
-> existing Scheduler
```

GitHub Actions remains transport only. The workflow must not treat this binding as cloud credentials or execution authorization. The later #1217 activation owns `id-token: write`, WIF/provider/service-account/IAM configuration, concrete GCP/IAP/OS Login calls, fixed-entrypoint deployment, and the bounded live smoke test under its separate authorization.

Rollback is repository-only: revert this module, its focused tests, and this note. No external state is created by this seam.
