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

Before confirmation, text and JSON show the bounded account identity, exact
version, sanitized executable basename plus a digest of its full path, and required/optional capability decisions.
A stable operation identity binds target, title/body identity, labels, validation,
and command semantics for repeat detection. A separate fresh confirmation
fingerprint also binds invocation ID, account, capabilities, and executable path.
Changing either operation or execution evidence invalidates confirmation.

## Process boundary

```text
gh issue create --repo=TARGET --title=TITLE --body-file=- --label=LABEL...
```

The argv is immutable; user values use `--flag=value`; the UTF-8 body uses stdin.
Confirmed success requires matching expected/written byte counts, successful
writer completion, and no write or close error; body content is never evidence.
The runner uses `shell=False`, bounded timeout and concurrent bounded capture,
terminates timed-out/interrupted children, and performs no retry, auth refresh,
account switch, scope escalation, or temporary-file baseline. Unsupported
assignees, milestones, types, relationships, projects, and recovery are blocked.

## Mutation and recovery

Mutation states are `not-attempted`, `uncertain`, and `confirmed`. Only exit zero
plus complete stdin delivery and exactly one canonical HTTPS issue URL sets
`mutation_performed=true`. Userinfo, ports, encoded ambiguity, leading-zero
numbers, duplicate URLs, no URL, wrong-target output, nonzero exit, incomplete
stdin, timeout, or interruption remain uncertain,
include `mutation-uncertain`, preserve recovery evidence, and disable retry.

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

## Evidence safety and #605

Diagnostics redact token formats, authorization values, credential assignments,
private keys, credential URLs, ANSI/control sequences, submitted title/body/
labels, and excess output. Confirmation displays digests and counts, not raw
content. Public success URLs are reconstructed from the validated target and
canonical issue number rather than copied from process output. #605 must reuse
`issue_create.py` identity, runner, confirmation, redaction, executor, and parser;
it must not create a parallel live path.
Passing tests do not authorize a live create or merge.
