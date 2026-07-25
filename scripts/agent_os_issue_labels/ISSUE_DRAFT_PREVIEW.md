# Issue Draft Validation and GitHub Creation Adapter

## Offline validation

```bash
python -m scripts.agent_os_issue_labels.draft_cli \
  --input tests/fixtures/agent_os_issue_labels/draft_minimum_valid.json
```

The offline path renders through the canonical form, emits deterministic text or
JSON, performs no external write, and preserves:

```text
valid preview != readiness != approval != write authorization
write_authorized=false
mutation_performed=false
```

Stable offline exits remain `0` eligible, `10` warning, `20` manual review, `30`
validation failure, and `64` invalid input. Parser ambiguity, schema drift,
missing evidence, unsafe requests, and unknown values remain fail-closed.

## GitHub CLI adapter

```bash
python -m scripts.agent_os_issue_labels.issue_create_cli \
  --input draft.json --target Blummer92/agent-os
```

Without `--execute`, the command runs read-only capability, authentication, and
target checks, builds an operation fingerprint, and returns confirmation-needed
evidence. `--execute` requires the exact fingerprint phrase before one attempt.
Only `submission_eligible=true` may plan; warnings require exact acknowledgement.
Authentication and repository access never imply authorization.

## Target and capability checks

The explicit target is `[HOST/]OWNER/REPOSITORY`; it is never inferred from git,
`GH_REPO`, prior commands, or authentication. Read-only probes verify:

- bounded `gh` version evidence and required create flags;
- `gh auth status --active --hostname HOST` without token display;
- `gh repo view TARGET --json nameWithOwner,url,hasIssuesEnabled,isArchived`;
- exact target match, issues enabled, and repository not archived.

Capability, account, target, title/body digests, labels, warnings, and semantic
argv are bound into a domain-separated SHA-256 fingerprint.

## Process boundary

```text
gh issue create --repo=TARGET --title=TITLE --body-file=- --label=LABEL...
```

The argv is immutable; user values use `--flag=value`; the UTF-8 body uses stdin.
The runner uses `shell=False`, bounded timeout/output, no retry, no auth refresh,
no account switching, and no scope escalation. Assignees, milestones, type,
relationships, projects, and recovery execution are blocked, not omitted.

## Mutation and recovery

Mutation states are `not-attempted`, `uncertain`, and `confirmed`. Only exit zero
plus exactly one issue URL matching the explicit target sets
`mutation_performed=true`. Timeout, interruption, nonzero exit, no URL, multiple
URLs, or wrong-target output remain uncertain, preserve recovery evidence, and
disable automatic retry.

| Exit | Meaning |
|---:|---|
| `0` | confirmed issue creation |
| `70` | confirmation missing/cancelled/stale or warning rejected |
| `71` | `gh` unavailable |
| `72` | capability unsupported |
| `73` | authentication/account failure |
| `74` | target invalid or mismatched |
| `75` | authorization absent or optional metadata unsupported |
| `76` | command failure |
| `77` | timeout or interruption |
| `78` | malformed success output |
| `79` | wrong-target or uncertain mutation |
| `80` | repeated operation fingerprint |

## Evidence safety and #605

Diagnostics redact tokens, auth headers, credential assignments, private keys,
credential URLs, ANSI controls, and excessive output. Reports contain body digest
and byte count, never body or environment secrets. #605 must reuse
`issue_create.py` models, runner, confirmation, redaction, argv builder,
fingerprint, executor, and parser; it must not create a parallel live path.
Passing tests do not authorize a live create or merge.
