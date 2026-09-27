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

## Production issue creation

GitHub MCP is the repository owner's selected bounded production issue-creation path as proven by #605. This document owns only the offline draft/validation contract; connected mutation authorization, duplicate review, canonical readback, and lifecycle policy remain with their existing governed GitHub owners.

The retired local `gh issue create` adapter is no longer a supported production entrypoint. Do not recreate a subprocess CLI transport here.

## Evidence safety

Offline draft and validation output remains non-authorizing and performs no mutation. Connected GitHub writes require their existing governed authorization and canonical readback contracts. Passing tests never authorizes issue creation, merge, or lifecycle mutation.
