# First-run authorized-validation lifecycle start (#1972)

> **Retired — GCE Wave 1.** The `/agent-os validate-first-run` selector is no
> longer admitted by `github_issue_comment_ingress` (ignored as
> `malformed-trigger`, no trigger identity, no execution). Its GCE transport
> was already removed in #3233 (`first_run_validation_gce.py` deleted; the
> adapter carries no first-run branch) and the Codespaces-first route resolves
> any stale accepted envelope to `preferred="none"`. The body below describes
> the historical lifecycle only; do not treat it as a live route. The
> `first_run_candidate_sha_or_none` transport field is retained (always null)
> for stored-evidence schema compatibility.

## Selector

The retired bounded GitHub issue-comment selector was exactly:

```text
/agent-os validate-first-run <candidate-sha>
```

`candidate-sha` was exactly 40 lowercase hexadecimal characters. Repository and issue identity came from the trusted GitHub event envelope. The ingress result carried only `first_run_candidate_sha_or_none`; it carried no argv, shell text, approval/evidence JSON, authority booleans, store paths, credentials, or runtime configuration.

Equivalent comments for the same repository, issue, and candidate SHA converged to one deterministic logical trigger identity. A different candidate SHA produced a different trigger identity. Transport admission remained non-authorizing: execution, Scheduler invocation, and side effects remained false.

## Transport route

`github_issue_comment_ingress` accepted the selector and carried the candidate
identity on `first_run_candidate_sha_or_none`. Transport reconstruction in
`gce_gcloud_adapter._ingress_from_file` preserves that field, and
`execute_transport` formerly routed `accepted-first-run-validation-envelope` to
`first_run_validation_gce.execute_first_run_validation_transport` before the
generic #1217 control binding (`first_run_validation_gce.py` was deleted in
#3233, and the adapter carries no first-run branch anymore). Without both, an
accepted first-run envelope lost its candidate identity and fell through to
the Scheduler control path, which cannot carry it.

The transport performed, in order: ingress identity validation, OIDC claims
check, bounded cold start when the approved host was STOPPED, fixed-entrypoint
readiness probe, then exactly one `GcloudIapAdapter.validate_first_run` call.
That method built the fixed host command from the trusted repository/issue plus
the 40-hex SHA — there was no argv parameter — and rejected returned evidence
whose repository, issue, or candidate identity drifted, or that reported a crossed
Scheduler/publication/lease/resume boundary.

When this first-run operation owned the cold start, #2428 composed the adapter's
existing opt-in stop capability and independently waited for provider-observed
STOPPED before reporting cleanup. A host that was already RUNNING was never
claimed or stopped by this first-run transport. Missing shutdown capability,
stop failure, or unconfirmed provider terminal state was reported as bounded
`needs-decision` evidence rather than as successful cleanup. No independent
shutdown authority, second lifecycle controller, or unconditional `finally:
stop` path was introduced.

## Trusted-host composition

The composition below documents the historical entrypoint module, which was
deleted by #3233. Neither `first_run_validation_entrypoint` nor its
`compose_first_run_validation` function is present or callable now. Wave 1
also retired the issue-comment selector; this is historical evidence only.

The removed `first_run_validation_entrypoint.compose_first_run_validation`
was designed to compose the then-existing owners in order, failing closed
between steps:

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
never creates a command surface or widens authority. The former composition did not own an independent validation, approval,
currentness, custody, evidence, persistence, Scheduler, lease, transport, or
retry system; it was designed to call each existing owner once.

## Existing owners reused

The retired selector did not create a second validation, approval, currentness, custody, Scheduler, lease, or persistence system. Its historical downstream dependencies were:

- #1982/#2309: production human approval and durable approval custody;
- #753/#755: approval applicability and execution-candidate compilation;
- #757/#1970: authorized-validation request and first-run residual invalidation projection;
- #1929: trusted-host current-state/authorization reacquisition and production authorized-validation caller;
- #1830: successful authorized-validation source capture;
- #1412/#1978: existing pre-publication evidence store.

## Activation boundary

`gce_gcloud_adapter.py` no longer carries the fixed `validate-first-run` host
operation (#3233 removed its transport; GCE Wave 1 retired the ingress
selector). The composition contract above describes a deleted entrypoint,
not a preserved module or a live execution route. Other GCE control paths
remain separately governed; nothing here authorizes GitHub Actions workflow
mutation, IAM/WIF changes, VM/host deployment, or live Scheduler/GCE execution.

Historically, host-state acquisition and the workflow/transport invocation
required separate authorization. The former
`first_run_validation_entrypoint.main` failed closed with
`first-run-host-state-activation-required`; both that entrypoint and
`first_run_validation_gce.main` were deleted by #3233. The remaining ingress
selector was retired in Wave 1. No current first-run runtime, importable
entrypoint, or activation path should be inferred from these historical steps.
