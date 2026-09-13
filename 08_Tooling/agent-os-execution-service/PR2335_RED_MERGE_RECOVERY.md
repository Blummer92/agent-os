# PR #2335 Red-Merge Recovery Evidence

## Purpose

Preserve the canonical recovery evidence for issue #2337 without rewriting the merged #2335 history or weakening Agent OS validation behavior.

## Failed merge lineage

- Parent capability mission: #2283
- Merged PR: #2335
- Exact PR head: `9ebebab1a99e618ae239932dea39f13fe812a640`
- Failed validation run: `34785530832`
- Failed job: `Run aggregate validation` / `103800204067`
- Merge commit now on `main`: `a2a26ed33cb8234b32209a9f2d7ca9414411e463`

The sibling `Run validation plan=success` result never overrides the failed aggregate validation gate.

## Recovery attempt #2339

Recovery PR #2339 was opened from current `main` to reacquire exact-head validation of the merged tree. Its first recovery commit intentionally had the same tree as `main`. GitHub accepted the commit, but the Agent OS Validation Gate correctly rejected the PR during `Compute canonical validation plan` because the pull request changed-file set was empty. Aggregate validation was therefore skipped.

That failure is preserved as a failed-repair attempt. The recovery does **not** change the validation workflow to permit empty PRs. Instead, this evidence file gives #2339 a real bounded change while documenting why the no-diff probe failed.

## Safety contract

For this recovery lineage:

- a red, cancelled, timed-out, stale, pending, or otherwise non-green required exact-head gate blocks merge;
- a green sibling check cannot mask a failed aggregate check;
- no historical validation result can be reported as green when canonical GitHub evidence says failure;
- merged #2335 history is not rewritten;
- no Notion, Drive, classroom, credential, production, protected-setting, or other external write is authorized by this recovery artifact;
- #2283 must not resume its live Notion smoke test until the #2335/#2337 recovery lineage has current green validation evidence.

## Rollback

Delete this file from the recovery branch if #2337 is abandoned. No runtime behavior depends on this record.
