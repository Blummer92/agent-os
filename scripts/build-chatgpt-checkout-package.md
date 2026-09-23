# build-chatgpt-checkout-package.sh

Builds one deterministic, exact-head Agent OS ZIP for offline ChatGPT code-execution
validation from an explicitly supplied branch, tag, or exact 40-character commit SHA.
It invents no checkout, fetch, worktree, or repository-state system: that is delegated
to `scripts/prepare-issue-worktree.sh` (#807), which reuses the fetch-retry contract
in `scripts/verify-repo-state-contract.md` (#621).

## Non-authorization

Successful packaging never implies implementation, execution, GitHub-write, or merge
authority, nor Ready-for-Review, merge, or issue completion. Every authority field in
its evidence is `false` on every outcome. It never commits, pushes, opens/edits a PR,
merges, closes issues, modifies labels, invokes providers, or performs any
GitHub-lifecycle or external-system write.

## Syntax and workflow

```bash
scripts/build-chatgpt-checkout-package.sh \
  --repository <owner/name> --issue <n> --ref <branch|tag|sha40> \
  --output <absolute .zip path> \
  [--worktree-root <absolute path>] [--base-ref <branch>]
```

Run from inside an existing Agent OS checkout, same as `prepare-issue-worktree.sh`;
`--output` must be absolute and end in `.zip`. Upload the resulting ZIP to the ChatGPT
execution container. Before trusting a run inside it, compare `resolved_sha` in the
stdout evidence (or in `agent-os-chatgpt-package-manifest.json` inside the ZIP)
against the live GitHub PR head — a mismatch means the wrong commit. A package is a
snapshot, not a live view: rebuild whenever that head moves.

## Package contents

Resolution semantics are exactly `prepare-issue-worktree.sh`'s: a local branch, a
remote-only branch, a tag, or an exact lowercase 40-hex SHA — prefer a SHA when
`requested_ref` and `resolved_sha` must match by construction. See
`scripts/prepare-issue-worktree.md` for the dirty/fetch/conflict modes this command
surfaces verbatim.

**Packaged bytes are read from `RESOLVED_SHA`, never from the worktree.** The command
re-verifies the resolved commit, enumerates its tree, and reads each blob by object
ID, so a tracked file edited after the clean-state check cannot reach the archive or
change the digest. Every tracked entry is inspected before exclusion filtering: modes
`100644` and `100755` are packaged, while symlinks (`120000`), gitlinks/submodules
(`160000`), and any other mode are rejected outright (exit 11) — a symlink is never
dereferenced, and one matching an exclusion pattern is still refused rather than
silently dropped.

Untracked caches, ignored credentials, and editor state are excluded by construction;
as defense in depth, tracked paths matching the static credential and cache list
(`EXCLUDE_PATTERNS` in the script) are also excluded and logged to stderr. `.git`
internals are excluded; the archive carries a verified manifest instead.

## Manifest, stdout evidence, and verification

The ZIP stores `agent-os-chatgpt-package-manifest.json` — exactly once; a commit
tracking that reserved pathname is rejected — holding identity (`repository`,
`issue_number`, `requested_ref`, `resolved_ref`, `resolved_sha`, `base_ref`,
`base_sha`, `checkout_mode`), package facts (`package_format`,
`included_git_metadata`, `file_count`, `archive_sha256`, `working_tree_clean`),
provenance (`schema_name`, `schema_version`, `created_by_command_version`,
`side_effects_performed`), and the four `false` authority fields.

**stdout repeats those manifest fields and adds the command-result fields `status`,
`output_path`, and `reason`** — the two objects are related, not identical. Every
controlled outcome emits exactly one JSON object on stdout, serialized in one pass, so
any value (including a path containing quotes, backslashes, or spaces) is escaped
rather than able to break the document; diagnostics go to stderr. Before success is
reported, the finished archive is reopened and its entry names, uniqueness, expected
file set, stored manifest, and recomputed digest are re-derived.

**Determinism boundary:** `archive_sha256` is a semantic digest over sorted
`[canonical_path, mode_category, byte_size, sha256(content)]` tuples for every
included file — independent of ZIP compression, host paths, usernames, and timestamps
(entries use a fixed 1980-01-01 date and normalized permissions). It excludes the
manifest entry itself, avoiding a circular self-reference, so two packages from the
same commit always match; line endings are never transformed.

## Publication, replacement, and cleanup

The archive is written to a private `0600` temporary file in the destination
directory, verified there, then published with an exclusive no-replace link. An
existing file, directory, symlink, or dangling symlink at `--output` fails closed
(exit 10) — the destination is never followed or overwritten, and the temporary file
is removed on any failure. An existing `agent-os-local.zip` is never touched: build at
a new path, verify it, then replace the old ZIP by hand. Deleting the output ZIP fully
reverses a run; no repository, GitHub, or credential write occurs.

An operator-supplied `--worktree-root` is never removed. A disposable worktree this
command created is removed only once verified clean; tracked changes, untracked files,
unverifiable cleanliness, or a refused removal preserve it as evidence with a bounded
stderr note.

Tests: `tests/test_build_chatgpt_checkout_package.py` (`./scripts/validate-all.sh`).
