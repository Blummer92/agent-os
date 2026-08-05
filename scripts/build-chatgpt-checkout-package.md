# build-chatgpt-checkout-package.sh

Builds one deterministic, exact-head Agent OS ZIP for offline ChatGPT
code-execution validation, from an explicitly supplied branch, tag, or exact
40-character commit SHA. It invents no checkout, fetch, worktree, or
repository-state system: all of that is delegated to
`scripts/prepare-issue-worktree.sh` (#807), which reuses the canonical
fetch-retry contract in `scripts/verify-repo-state-contract.md` (#621).

## Non-authorization

Successful packaging never implies implementation, execution, GitHub-write,
or merge authority, and never implies Ready-for-Review, merge, or issue
completion. Every authority field in its evidence is `false` on every
outcome. It never commits, pushes, opens/edits a PR, merges, closes issues,
modifies labels, invokes providers, or performs any other GitHub-lifecycle or
external-system write.

## Syntax

```bash
scripts/build-chatgpt-checkout-package.sh \
  --repository <owner/name> --issue <n> --ref <branch|tag|sha40> \
  --output <absolute .zip path> \
  [--worktree-root <absolute path>] [--base-ref <branch>]
```

Run from inside an existing Agent OS checkout, same as
`prepare-issue-worktree.sh`. `--output` must be absolute, end in `.zip`, and
not already exist — no replacement mode is authorized, so a collision fails
closed (exit 10).

## Desktop, mobile, and ChatGPT workflow

```bash
cd ~/agent-os
scripts/build-chatgpt-checkout-package.sh \
  --repository Blummer92/agent-os --issue 881 \
  --ref agent/881-chatgpt-exact-head-package \
  --output ~/agent-os-packages/issue-881.zip
```

Upload the resulting ZIP to the ChatGPT execution container. Before trusting
a validation run inside it, compare `resolved_sha` in the stdout evidence (or
`agent-os-chatgpt-package-manifest.json` inside the ZIP) against the live
GitHub PR head for the same branch — a mismatch means the wrong commit.
Rebuild whenever that head moves; a package is a snapshot, not a live view.

## Branch, tag, and SHA usage; package contents

Resolution semantics are exactly `prepare-issue-worktree.sh`'s: a local
branch, a remote-only branch, a tag, or an exact lowercase 40-hex SHA. Prefer
an exact SHA when `requested_ref` and `resolved_sha` must match by
construction. See `scripts/prepare-issue-worktree.md` for the full table and
the dirty/fetch/conflict modes this command surfaces verbatim.

Only files `git ls-files` reports as tracked at the resolved commit are
included — untracked caches, ignored credentials, and editor state are
excluded by construction. As defense in depth, tracked paths matching a
static list (`.env`, `*.pem`, `*.key`, `id_rsa*`, `*credentials*`,
`*secret*`, `__pycache__/`, `.venv/`, `node_modules/`, `dist/`, `build/`,
`*.zip`) are still excluded and logged to stderr. `.git` internals are
excluded; the archive carries a verified manifest instead. A tracked symlink
is never dereferenced or silently dropped: its mode is read from
`git ls-files -s`, and packaging is refused outright (exit 11) if any
included path is one.

## Manifest fields and verification

`agent-os-chatgpt-package-manifest.json` is written inside the ZIP and the
same object is emitted on stdout: identity (`repository`, `issue_number`,
`requested_ref`, `resolved_ref`, `resolved_sha`, `base_ref`, `base_sha`,
`checkout_mode`), package facts (`package_format`, `included_git_metadata`,
`file_count`, `archive_sha256`, `working_tree_clean`), provenance
(`schema_name`, `schema_version`, `created_by_command_version`,
`side_effects_performed`), and the four `false` authority fields — verified
by reopening the archive and recomputing the digest before returning success.

**Determinism boundary:** `archive_sha256` is a semantic digest over sorted
`[canonical_path, mode_category, byte_size, sha256(content)]` tuples for
every included file — independent of ZIP compression, host paths,
usernames, and timestamps (entries use a fixed 1980-01-01 date and
normalized permissions). It excludes the manifest entry itself, avoiding a
circular self-reference, so two packages built from the same source tree by
the same command version always match, even across hosts. Line endings are
never transformed: files are copied byte-for-byte from the worktree.

## Replacing the stale `agent-os-local.zip`, and cleanup

This command never touches an existing `agent-os-local.zip`. Build a new
package at a different path, verify its manifest against the live PR head,
then let the operator replace the old ZIP by hand outside this tool. Nothing
is rolled back: no repository, GitHub, or credential write occurs. An
operator-supplied `--worktree-root` is never removed; a disposable worktree
this command created is removed only once confirmed clean, otherwise
preserved with a bounded stderr note. Deleting the output ZIP fully
reverses a run.

Tests: `tests/test_build_chatgpt_checkout_package.py` (`./scripts/validate-all.sh`).
