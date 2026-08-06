# Agent OS GitHub Git Objects

This package implements the local, governed capability requested by Issue #920 and needed to unblock the publication checkpoint in Issue #917. It does **not** modify or replace the hosted ChatGPT GitHub connector.

## Boundary

The package exposes a typed Git Database transport and a two-phase atomic commit operation for existing blobs. It remains separate from `scripts/agent_os_github_issue_provider`, whose contract is issue-specific and read-only.

Supported transport operations are limited to:

- read one branch ref;
- read one Git commit;
- read one Git tree;
- read one Git blob;
- create one derived tree from an exact base tree;
- create one commit with one exact parent;
- compare the unattached commit with its parent;
- update one non-protected branch ref with `force=false`.

There is no arbitrary URL, HTTP method, REST escape hatch, GraphQL operation, issue or pull-request mutation, workflow dispatch, merge, settings mutation, or credential-management operation.

## Planning and confirmation

`prepare_atomic_commit_from_blobs` performs reads only. It verifies the branch head, reads the parent commit's exact `tree_sha`, verifies every supplied blob, and produces a deterministic operation fingerprint.

`execute_atomic_commit_from_blobs` requires a matching immutable confirmation. It rechecks the branch, creates one tree and one commit, validates the unattached commit's exact changed-path set and blob identities, rechecks the branch again, and updates the ref non-force.

Missing, cancelled, stale, or mismatched confirmation performs zero writes.

## Failure behavior

The operation fails closed when repository identity, branch identity, SHAs, entries, confirmation, compare evidence, or concurrency state do not match the request. Objects created before a later gate fails are returned as unattached audit objects.

Read retries are bounded to transient failures. Git tree, commit, and ref writes are never automatically retried. A dropped or ambiguous write response is returned as `mutation-uncertain`.

## Security and authority

- `main` and `master` are blocked by the public request model.
- Only mode `100644` and type `blob` are supported.
- Entries must exactly match the caller's allowlist.
- Path traversal, control characters, duplicate paths, unsupported modes, unsupported types, and malformed SHAs are rejected before transport use.
- Authority fields in results are fixed false.
- Credentials come only from an already-provisioned `GITHUB_TOKEN` or `GH_TOKEN`; the CLI does not create, refresh, print, or switch credentials.
- Live execution requires separate repository-owner authorization. Tests use injected fakes and perform no network or GitHub mutation.

## CLI

Read-only planning:

```bash
python -m scripts.agent_os_github_git_objects.cli plan --manifest manifest.json
```

Separately confirmed execution:

```bash
python -m scripts.agent_os_github_git_objects.cli execute \
  --manifest manifest.json \
  --confirmation-file confirmation.json
```

Both JSON inputs are closed schema. Stdout is stable JSON; bounded diagnostics go to stderr. The CLI has no `--force`, raw endpoint, merge, issue, PR, workflow, or settings option.

## Rollback

Remove this package, its tests, the `scripts/README.md` entry, and the #920 changelog entry. Historical Git objects and commits are not rewritten. Any unattached objects remain audit evidence and must never be silently attached to another ref.

## Limitations

The first version supports ordinary UTF-8 repository file blobs only. It does not support executable files, symlinks, submodules, tree entries, deletions, merge commits as the publication parent, protected branches, generic repository administration, or live #917 publication as part of its tests.
