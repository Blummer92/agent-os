# Issue Draft Validation and GitHub Creation Adapter

## Offline validation

```bash
python -m scripts.agent_os_issue_labels.draft_cli \
  --input tests/fixtures/agent_os_issue_labels/draft_minimum_valid.json
```

The offline path renders through the canonical form, emits deterministic text or
JSON, performs no write, and preserves:

```text
valid preview != readiness != approval != write authorization
write_authorized=false
mutation_performed=false
```

Offline exits remain `0` eligible, `10` warning, `20` manual review, `30`
validation failure, and `64` invalid input. Parser ambiguity, schema drift,
missing evidence, unsafe requests, and unknown values remain fail-closed.

## GitHub CLI adapter

```bash
python -m scripts.agent_os_issue_labels.issue_create_cli \
  --input draft.json --target Blummer92/agent-os
```

Without `--execute`, the command performs read-only capability, authentication,
and target checks and returns confirmation-needed evidence. `--execute` requires
one exact fresh confirmation. Only `submission_eligible=true` may plan; warnings
require exact acknowledgement. Authentication and access never authorize writes.

## Identity, target, and capability

The explicit target is `[HOST/]OWNER/REPOSITORY`; it is never inferred from git,
`GH_REPO`, `GH_HOST`, prior commands, or authentication. Read-only probes verify:

- one resolved `gh` executable and bounded version evidence;
- exact required create flags; version text is informational;
- `gh auth status --active --hostname HOST` without token display;
- matching, non-archived repository metadata with issues enabled.

Before confirmation, text and JSON show bounded account, version, executable identity, and required/optional capability decisions.
A stable operation identity binds target, title/body identity, labels, validation,
and command semantics for repeat detection. A separate fresh confirmation
fingerprint also binds invocation ID, account, capabilities, and executable path.
Changing either operation or execution evidence invalidates confirmation.

## Process boundary

```text
gh issue create --repo=TARGET --title=TITLE --body-file=- --label=LABEL...
gh issue view ISSUE --repo=TARGET --json number,url,title,body,labels
```

The immutable create argv uses `--flag=value`; the UTF-8 body uses stdin. Confirmed
creation requires complete stdin delivery and one canonical issue URL. The same
`GhRunner` then performs exactly one read-only issue-view and verifies number, URL,
title, body, and labels before final success. The runner uses `shell=False`, bounded
timeout/capture, no automatic retry or corrective mutation, no auth refresh/account
switch, and no scope escalation. Unsupported optional metadata remains blocked.

## Mutation and recovery

Mutation states remain `not-attempted`, `uncertain`, and `confirmed`. A confirmed
create keeps `mutation_performed=true` even if post-create read-back fails. Read-back
failure blocks verification, preserves the created issue identity, disables retry,
and requires manual inspection; it never edits, closes, deletes, or relabels the
issue. Pre-confirmation/create ambiguity still uses `mutation-uncertain`.

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
| `80` | repeated stable operation identity |
| `81` | confirmed creation but read-back verification failed |

## Evidence safety and #605

Diagnostics redact token formats, authorization values, credential assignments,
private keys, credential URLs, ANSI/control sequences, submitted title/body/
labels, and excess output. Confirmation displays digests and counts, not raw
content. Public success URLs are reconstructed from the validated target. #605
must reuse this create-plus-read-back production path, including the same runner,
identity, confirmation, redaction, parser, and verifier; no parallel live path or
ad hoc `gh issue view` command is permitted.
Passing tests do not authorize a live create or merge.
