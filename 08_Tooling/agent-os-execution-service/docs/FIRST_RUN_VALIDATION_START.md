# First-run authorized-validation lifecycle start (#1972)

## Selector

The bounded GitHub issue-comment selector is exactly:

```text
/agent-os validate-first-run <candidate-sha>
```

`candidate-sha` is exactly 40 lowercase hexadecimal characters. Repository and issue identity come from the trusted GitHub event envelope. The ingress result carries only `first_run_candidate_sha_or_none`; it carries no argv, shell text, approval/evidence JSON, authority booleans, store paths, credentials, or runtime configuration.

Equivalent comments for the same repository, issue, and candidate SHA converge to one deterministic logical trigger identity. A different candidate SHA produces a different trigger identity. Transport admission remains non-authorizing: execution, Scheduler invocation, and side effects remain false.

## Existing owners reused

The selector does not create a second validation, approval, currentness, custody, Scheduler, lease, or persistence system. Current architecture already owns the downstream pieces:

- #1982/#2309: production human approval and durable approval custody;
- #753/#755: approval applicability and execution-candidate compilation;
- #757/#1970: authorized-validation request and first-run residual invalidation projection;
- #1929: trusted-host current-state/authorization reacquisition and production authorized-validation caller;
- #1830: successful authorized-validation source capture;
- #1412/#1978: existing pre-publication evidence store.

## Activation boundary

Current `gce_gcloud_adapter.py` has no fixed `validate-first-run` host operation, and the governed GitHub Actions -> WIF -> GCE/IAP route is workflow/deployment controlled. This issue's ordinary Safe Implementation Lane does not authorize GitHub Actions workflow mutation, IAM/WIF changes, VM/host deployment, or live Scheduler/GCE execution.

Therefore this repository change intentionally stops at the bounded selector contract and regression evidence. Making the selector live requires a separately authorized workflow/transport + host-runtime activation that reuses the existing fixed-operation architecture; it must not be implemented as arbitrary command transport or a second router.
