# Trusted CI status publisher — staged pilot

## Purpose

A privileged commit-status publisher must not execute pull-request-controlled code. This pilot adds a separate default-branch `workflow_run` subscriber and a narrowly scoped, provider-evidence-only decision module. The pilot status is **not required** and is intentionally named `agent-os/trusted-aggregate-pilot`.

## Provenance and boundaries

- Source workflow: `.github/workflows/agent-os-validation.yml` (`Agent OS Validation Gate`).
- Candidate: the source run's exact `head_sha`, associated with an **open, non-Draft, same-repository PR** targeting `main` and still current at query time.
- Source jobs: read via the authenticated GitHub API for the **exact run attempt**, not artifact-supplied claims.
- Four named jobs and critical steps must have successful conclusions; failures, missing jobs, ambiguous identities, or missing steps cannot produce success.
- A newer run/attempt supersedes stale evidence for the same SHA.
- Changes to validation policy or trusted test-discovery infrastructure cannot receive a pilot success without a separately reviewed authorization procedure. The authority guard covers all four explicitly installed pip/editable-project inputs, dynamically selected package/test configuration files (Python and npm), composite actions, and workflow files. This is intentionally conservative: even a legitimate package upgrade must use the independently reviewed authority-change route rather than inherit a normal pilot success.
- The privileged checkout action is pinned to the immutable commit `3d3c42e5aac5ba805825da76410c181273ba90b1` (`actions/checkout` v7.0.1, verified against the official upstream GitHub release tag on 2026-11-08). Upgrading it requires a reviewed SHA and a fresh exact-head trust review.
- The subscriber checks out only the repository's default branch with `persist-credentials: false` and **never checks out or runs PR content**. No artifact content is executed or imported. Credentials are available only to the trusted provider-query step.
- Fork PRs, Draft PRs, dispatches, main-push runs, and unassociated runs do not mint this pilot context.
- Provider failures yield no authority. A missing result is **not** a pass.
- When all required source jobs and steps have provider-backed success **but the PR changes CI authority**, this non-required pilot publishes `pending`, not `success`. The pending state explicitly means *independent trust review still required*; it is neither certification nor a merge-required approval. Known source failures, missing or conflicting jobs, and failed/missing step evidence remain `failure`/`error`, even on authority-changing PRs.
- A green publisher **workflow job** after a `pending` publication proves only that the pending status was delivered successfully. It does **not** make the pilot trusted or green. Pending may persist until a separately governed qualification route exists; do not automatically convert it to success.

## Deliberately incomplete

This is an additive *pilot*, not the enforcement repair. The existing `validate` and `aggregate-gate` jobs still possess `statuses: write`; existing ruleset #19123362 still requires `agent-os/authoritative-aggregate`. Until an independently reviewed cutover removes these write grants and changes the ruleset, **the P0 finding remains OPEN**.

The pilot also does not certify that candidate-controlled test code is semantically effective or that CodeQL is merge-required. It rejects changes to known validation authority files as an early policy control, but code-only green source jobs are not sufficient proof against all possible test bypasses.

## Safe staged cutover

1. Review this pilot in Draft. Run its local tests and independent static/code review. Do not modify protection settings.
2. After owner authorization, merge only the additive pilot; observe its status on normal PRs and read provider evidence for both green and red cases.
3. Qualify missing-artifact, wrong-attempt, stale-PR, review-transition, and untrusted-workflow-change scenarios; check how reruns interact with previous successes. Formalize a human-reviewed route for CI-source changes.
4. In a **separate** authorized migration, disable `statuses: write` in both PR jobs, move final authority entirely into default-branch trusted code, and coordinate changing the required ruleset context with no unprotected window.
5. Execute hosted canaries and revert/stop upon any false green, publication anomaly, or incorrect check identity. Do not mark fully autonomous merging safe until CodeQL/review/freshness policies have their own proof.

## Verification

`python -m pytest -q tests/test_agent_os_trusted_status_publisher.py`

These tests are offline synthetic negative controls. They cannot certify hosted events, credentials, or GitHub ruleset behavior.
