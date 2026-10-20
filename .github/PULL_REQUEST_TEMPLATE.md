<!--
The PR owns implementation evidence. Do not repeat the issue
specification. See 01_Shared_Standards/github/issue-lifecycle-standard.md.
Exactly one open primary PR may claim an implementation issue.
-->

## Linked issue

Part of #N

<!--
Linkage is non-closing by default: replace N with the linked issue
number and keep the "Part of #N" (or "Refs #N") form unless closure is
intended and admitted.

GitHub treats a closing keyword followed by an issue number ANYWHERE in
the PR title or body as a closing reference — even negated ("does not
close" followed by a number), mid-sentence, or in examples — and closes
the issue at merge. This template therefore never pairs a closing keyword
with an issue number, and the PR body must not either: keep closing
wording away from issue numbers entirely.

Closing opt-in: to close the linked issue at merge, replace the line
above with a standalone closing-keyword line naming that issue. That is
admitted only when a closure admission for this exact issue exists at
merge time (see 01_Shared_Standards/github/issue-lifecycle-standard.md);
otherwise Ready admission and merge authorization fail closed. A
standalone "Non-closing:" directive line naming every referenced issue
is the explicit alternative declaration.
-->

## Criterion preservation

Linked issue: #N

<!--
Every acceptance criterion of the linked issue must be accounted for
below with its identity — its exact text — preserved. Complete the
per-criterion mapping, or replace it with the manual-review statement.
A dropped or reworded criterion is a manual-review item, never a silent
edit. Implementation handoffs carry criteria through the criterion
packet in scripts/agent_os_issue_acceptance/criterion_preservation.py,
which reports every criterion parsed from the canonical issue body and
flags any dropped or altered criterion as manual-review.
-->

Per-criterion mapping (one entry per acceptance criterion of the linked
issue, criterion text quoted unchanged):

- Criterion: "<criterion text, unchanged>" — Evidence: <where this PR satisfies it>

OR, when the criteria cannot be mapped one-to-one:

Manual review: criterion preservation could not be mapped one-to-one for
this PR. Unmapped criteria, quoted unchanged: <list>

## Summary

## Files changed

## Tests run

<!--
Include commands, results, and the exact tested SHA classification.
Use the canonical runner once for aggregate validation. When the issue
identifies focused tests, prefer passing them through --focused:

./scripts/validate-all.sh --focused tests/test_example.py --focused-maxfail 1

Report local branch-head SHA and pull-request synthetic-merge SHA separately.
Do not describe pull_request GITHUB_SHA as the branch head.
-->

## Docs updated

## Unresolved blockers

## Handoff recommendations

## Rollback

## Remaining risks
