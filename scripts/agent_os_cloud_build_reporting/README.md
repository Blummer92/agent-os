# Agent OS Cloud Build Reporting

Deterministic Cloud Build reporting contracts for the #685/#686 sequence.

## Core contract (#685)

The core is supplied-evidence-only and performs no network, GitHub, Cloud Build,
credential, filesystem, subprocess, environment, or clock access. It owns:

- terminal/non-terminal Cloud Build evidence normalization;
- exact repository + tested-SHA pull-request resolution;
- bounded, secret-safe comment rendering and stable managed markers.

Automatic PR resolution requires an authoritative supplied PR number matching
the exact repository and tested SHA, or exactly one supplied open candidate with
that exact identity. Ambiguous, closed, incomplete, malformed, wrong-repository,
or wrong-SHA evidence never resolves automatically.

Candidate intake is bounded by `MAX_PR_CANDIDATES` (64). Public rendered text
is sanitized and bounded; authority and side-effect flags remain false.

## Publication policy (#686)

`publication.py` is the thin domain policy around the canonical GitHub comment
operation. It does **not** implement a GitHub client, authentication, pagination,
retry transport, or a second comment API abstraction.

A connected caller supplies:

1. #685 evidence, exact-SHA PR resolution, and rendered projection;
2. a complete bounded snapshot of current PR conversation comments;
3. the result and complete canonical readback after any admitted mutation.

`plan_publication(...)` returns exactly one bounded action:

- `create` when no managed marker exists;
- `update` when exactly one managed marker exists with stale body content;
- `noop` when that managed comment is already byte-for-byte current;
- `manual-review` when target proof, comment completeness, marker identity, or
  uniqueness is not proven.

Unrelated human comments are ignored and never selected for edit/removal.
Multiple managed-marker matches fail closed rather than guessing.

Connected execution must use the existing canonical Agent OS GitHub operation
and shared request infrastructure established by #2507. The policy itself
performs zero writes. After a create/update attempt,
`reconcile_publication(...)` reuses the canonical #2785 comment-mutation
readback classifier and requires exact-body canonical readback before reporting
`converged`. An update additionally requires the same managed comment identity;
a matching body on a different comment is `uncertain`, not success.

Provider failure with complete evidence may be reported as safely retryable by
the shared readback contract. Incomplete/duplicate/mismatched readback is
uncertain and never authorizes a blind retry.

## Authority boundary

Cloud Build comments are supplemental informational evidence only. This package
does not authorize merge, review approval, required-check status, readiness,
issue lifecycle mutation, workflows, credentials, provider activation, or
production/external writes. Live credential/activation and bounded smoke tests
remain #687.

## Tests

```bash
python -m pytest -q tests/agent_os_cloud_build_reporting/test_core.py
python -m pytest -q tests/agent_os_cloud_build_reporting/test_publication.py
python -m pytest -q tests/agent_os_issue_acceptance/test_comment_mutation_readback.py
```
