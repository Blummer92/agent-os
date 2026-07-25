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

Stable offline exits remain `0` eligible, `10` eligible warning, `20` manual
review, `30` validation failure, and `64` invalid input or usage. Parser
ambiguity, schema drift, missing evidence, unsafe requests, and unknown values
remain fail-closed. Local duplicate evidence is advisory only.

## GitHub CLI adapter

```bash
python -m scripts.agent_os_issue_labels.issue_create_cli \
  --input draft.json --target Blummer92/agent-os
```

Without `--execute`, the command performs read-only capability, authentication,
and explicit-target checks, builds a deterministic operation fingerprint, and
returns confirmation-required evidence. `--execute` displays the sanitized plan
and requires the exact fingerprint phrase before one create attempt.

The adapter accepts only a merged `IssueDraftValidationResult` with
`submission_eligible=true`. Eligible warnings require exact warning
acknowledgement. Authentication and repository access never imply authorization.

## Target and capability checks

The target is explicit `[HOST/]OWNER/REPOSITORY`; it is never inferred from git,
`GH_REPO`, prior commands, or authentication state. Read-only probes verify:

- `gh` exists and reports a bounded version;
- required `gh issue create` flags are present;
- `gh auth status --active --hostname HOST` succeeds without token display;
- `gh repo view TARGET --json nameWithOwner,url,hasIssuesEnabled,isArchived`
  matches the target, is not archived, and has issues enabled.

Capability, account, target, title/body digests, labels, warnings, and semantic
argv are bound into a domain-separated SHA-256 operation fingerprint.

## Process boundary

The baseline argv is an immutable sequence:

```text
gh issue create --repo=TARGET --title=TITLE --body-file=- --label=LABEL...
```

User values use `--flag=value`; the UTF-8 Markdown body is passed only through
stdin. The runner uses `shell=False`, bounded timeout/output, no auto-retry, no
auth refresh, no account switching, and no scope escalation. Assignees,
milestones, type, parent/dependency links, project assignment, and recovery
execution are blocked rather than silently omitted.

## Mutation and recovery

Mutation states are `not-attempted`, `uncertain`, and `confirmed`. Only process
exit zero plus exactly one issue URL matching the explicit host/owner/repository
sets `mutation_performed=true`. Timeout, interruption, nonzero exit, no URL,
multiple URLs, or a wrong-target URL are uncertain, preserve recovery evidence,
and disable automatic retry.

Adapter exits are:

| Exit | Meaning |
|---:|---|
| `0` | confirmed issue creation |
| `70` | confirmation missing/cancelled/stale or warning not accepted |
| `71` | `gh` unavailable |
| `72` | required capability unsupported |
| `73` | authentication/account failure |
| `74` | target invalid, ambiguous, or mismatched |
| `75` | authorization absent or optional metadata unsupported |
| `76` | external command failure |
| `77` | timeout or interruption |
| `78` | malformed success output |
| `79` | wrong-target or uncertain mutation |
| `80` | repeated operation fingerprint |

## Evidence safety and #605

Diagnostics redact token formats, authorization headers, credential assignments,
private keys, credential URLs, ANSI controls, and excessive output. Command
reports contain a body digest and byte count, never the body or environment
secrets. #605 must reuse `issue_create.py` public models, runner, confirmation,
redaction, argv builder, fingerprint, executor, and parser; it must not create a
parallel live path. Passing tests do not authorize a live create or merge.
