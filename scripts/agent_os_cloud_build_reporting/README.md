# Agent OS Cloud Build Reporting

Pure-local, deterministic, supplied-evidence-only core for Cloud Build
reporting. Implements immutable models and functions for:

- normalizing terminal/non-terminal Cloud Build evidence;
- resolving pull-request identity only from an exact repository-and-SHA
  match;
- rendering a bounded, deterministic, secret-redacted comment projection.

## Scope

Owned by issue #685. No network, GitHub, Cloud Build, credential,
filesystem, subprocess, environment, or clock access exists in this
package. All inputs are supplied by the caller; nothing is fabricated,
inferred, or persisted.

Connected lookup and live PR comment publication belong to #686. Live
credential, trigger, and smoke-test activation belongs to #687.
Provider-neutral failure projection belongs to #694.

## Public contract

- `CloudBuildResultEvidence` — immutable evidence: build id, full 40-char
  tested SHA, repository, trigger/invocation ids, `overall_result`
  (`success`, `failure`, `timeout`, `cancelled`, `internal-error`,
  `unavailable`, `pending`, `malformed`), `failed_step`, `exit_code`,
  `observed_at`, `terminal`, `source_complete`.
- `PullRequestResolutionCandidate` — a supplied open/closed PR candidate:
  repository, PR number, head SHA, state, evidence source.
- `PullRequestResolutionResult` — `resolved | skipped | manual-review |
  invalid`, resolved PR number, bounded reason codes.
- `CloudBuildCommentProjection` — deterministic hidden marker, bounded
  rendered body, `side_effects_performed = False`,
  `execution_authorized = False`.

Functions: `normalize_cloud_build_evidence`, `resolve_pull_request`,
`render_comment_projection`, `serialize_projection`,
`compute_stable_marker`, `evidence_semantic_identity`, `is_same_build`.

## Resolution rules

Automatic resolution requires an authoritative supplied PR number that
matches the exact repository and tested SHA, or exactly one supplied open
candidate matching the exact repository and tested SHA. No match, multiple
matches, closed candidates, wrong repository, wrong SHA, or incomplete or
malformed evidence route to `skipped`, `manual-review`, or `invalid`.
Resolution never uses issue numbers, branch names, titles, comments, or
semantic similarity.

## Non-goals

No GitHub or Cloud Build API calls, no live PR comments, no `cloudbuild.yaml`
changes, no credentials, no persistence, and no merge, approval, or
required-check authorization. All authority and side-effect flags are fixed
`False`.

## Tests

```bash
python -m pytest -q tests/agent_os_cloud_build_reporting/test_core.py
```
