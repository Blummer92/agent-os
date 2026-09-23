# First-run authorized-validation lifecycle start (#1972)

## Selector

The bounded GitHub issue-comment selector is exactly:

```text
/agent-os validate-first-run <candidate-sha>
```

`candidate-sha` is exactly 40 lowercase hexadecimal characters. Repository and issue identity come from the trusted GitHub event envelope. The ingress result carries only `first_run_candidate_sha_or_none`; it carries no argv, shell text, approval/evidence JSON, authority booleans, store paths, credentials, or runtime configuration.

Equivalent comments for the same repository, issue, and candidate SHA converge to one deterministic logical trigger identity. A different candidate SHA produces a different trigger identity. Transport admission remains non-authorizing: execution, Scheduler invocation, and side effects remain false.

## Transport route

`github_issue_comment_ingress` accepts the selector and carries the candidate
identity on `first_run_candidate_sha_or_none`. Transport reconstruction in
`gce_gcloud_adapter._ingress_from_file` preserves that field, and
`execute_transport` routes `accepted-first-run-validation-envelope` to
`first_run_validation_gce.execute_first_run_validation_transport` before the
generic #1217 control binding. Without both, an accepted first-run envelope
loses its candidate identity and falls through to the Scheduler control path,
which cannot carry it.

The transport performs, in order: ingress identity validation, OIDC claims
check, host-running check, fixed-entrypoint readiness probe, then exactly one
`GcloudIapAdapter.validate_first_run` call. That method builds the fixed host
command from the trusted repository/issue plus the 40-hex SHA — there is no argv
parameter — and rejects returned evidence whose repository, issue, or candidate
identity drifts, or that reports a crossed Scheduler/publication/lease/resume
boundary. Every other outcome is a bounded non-authorizing envelope.

## Trusted-host composition

`first_run_validation_entrypoint.compose_first_run_validation` composes the
existing owners once each, in order, failing closed between steps:

1. trusted GitHub identity (`FirstRunValidationIdentity`);
2. current candidate/provenance and current approval (`FirstRunHostState`);
3. #1985 fresh pre-validation (`prepare_fresh_pre_validation`);
4. exact fixed validation-profile match
   (`resolve_fixed_first_run_validation_id`, restricted to the existing fixed
   GCE dev-validation runner's own `VALIDATION_REGISTRY`);
5. existing GCE dev-validation runner (`run_fixed_validation` seam);
6. observed validation evidence (`observed_command_from_fixed_gce_evidence`,
   `supplied_command_results_from_dev_validation`);
7. existing PR-less evidence bundle
   (`build_pre_pr_validation_evidence_bundle`; no pull-request identity is ever
   fabricated, and the PR-carrying builder is not imported);
8. bound RequiredEnvironmentSpec (`build_candidate_environment_provenance`);
9. non-authorizing execution-packet identity (`prepare_execution_packet`);
10. current execution-authorization reacquisition
    (`reacquire_execution_authorization`);
11. #1970 request (`build_first_run_authorized_validation_request`);
12. #1929/#1830 bounded source/evidence capsule (`run_authorized_validation`
    seam).

`run_fixed_validation` and `run_authorized_validation` are named seams whose
bindings are the existing owners. Supplying a seam selects an existing owner; it
never creates a command surface or widens authority. The composition holds no
validation, approval, currentness, custody, evidence, persistence, Scheduler,
lease, transport, or retry system of its own, and calls each owner exactly once.

## Existing owners reused

The selector does not create a second validation, approval, currentness, custody, Scheduler, lease, or persistence system. Current architecture already owns the downstream pieces:

- #1982/#2309: production human approval and durable approval custody;
- #753/#755: approval applicability and execution-candidate compilation;
- #757/#1970: authorized-validation request and first-run residual invalidation projection;
- #1929: trusted-host current-state/authorization reacquisition and production authorized-validation caller;
- #1830: successful authorized-validation source capture;
- #1412/#1978: existing pre-publication evidence store.

## Activation boundary

`gce_gcloud_adapter.py` now carries the fixed `validate-first-run` host
operation and the composition contract above, but the governed GitHub Actions ->
WIF -> GCE/IAP route remains workflow/deployment controlled. This issue's
ordinary Safe Implementation Lane does not authorize GitHub Actions workflow
mutation, IAM/WIF changes, VM/host deployment, or live Scheduler/GCE execution.

Two things therefore remain separately authorized, and the repository fails
closed on both rather than inventing a fallback:

- host-state acquisition. `first_run_validation_entrypoint.main` validates the
  fixed selector and then raises `first-run-host-state-activation-required`. The
  module imports cleanly (so the readiness probe is honest) but performs no
  composition until the host-runtime activation binds `FirstRunHostState` and
  the two seams to their production owners.
- the workflow/transport wiring that invokes
  `first_run_validation_gce.main` on an accepted envelope.

Both must reuse the existing fixed-operation architecture; neither may be
implemented as arbitrary command transport or a second router.
