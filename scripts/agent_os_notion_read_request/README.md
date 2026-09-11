# Agent OS Bounded GitHub-Controlled Notion Read Request (#2283)

This package implements the GitHub-side admission, request vocabulary, and
sanitized public result projection for the #2283 read path.

## Architecture

```text
ChatGPT
-> GitHub MCP
-> `/agent-os notion-read <request-id>` issue comment
-> existing governed issue_comment ingress admission
-> GitHub Actions standard hosted runner
-> existing #936 read-only Notion adapter
-> sanitized bounded result on the public GitHub evidence surface
-> ChatGPT reads the result through GitHub MCP
```

GitHub stays the Agent OS governance/control surface. Notion stays the working
curriculum and Visual Asset Library source. The public result is a
request-scoped projection, never a curriculum or asset source of truth.

## Boundary

This package adds no Notion client, curriculum context engine, current-state
model, asset registry, cache, queue, scheduler, retry loop, proxy, or source of
truth. It composes existing capabilities only:

| Capability | Owner |
| --- | --- |
| read-only Notion adapter and `NOTION_TOKEN` contract | #936 |
| request-sensitive curriculum read planning | #980 |
| relation-first Visual Asset Library retrieval | #971 |
| provider-neutral evidence assembly | #975 |
| currentness, conflict, and authority resolution | #973 |
| execution-surface routing and read-only action bound | #2282 |
| low-trust issue-comment transport admission | governed ingress |

Routine reads never require GCE. An accepted notion-read envelope is explicitly
refused by the GCE control path so it cannot acquire that dependency by
falling through.

## Request vocabulary

The executable comment carries only a finite repository-owned slug. It never
carries a Notion id, URL, property name, filter, API path, HTTP method, shell
fragment, or free-form teacher text.

```text
/agent-os notion-read photography-foundations-visual-assets
```

`notion_read_catalog.json` is the only place a slug becomes a source identity.
It declares the finite request classes (`canonical-unit`, `current-curriculum`,
`visual-assets`, `teacher-modeling`, `packet-materials`), the canonical unit
identity bindings, and the source allowlist.

## What the catalog may and may not own

The catalog is **binding and policy configuration only**. It carries request
ids, provider identity bindings, the finite request-class vocabulary, the
publication content class, and the operator-controlled verification state.

It must never carry curriculum semantic truth. In particular it may not declare
a canonical unit's status: #973 decides disposition from that status, and
`_disposition` returns `needs-decision` for any non-active unit. A
repository-declared status would make that protection unreachable and would
drift from Notion the moment a unit is archived, split, or merged. Loading
therefore rejects a catalog that declares `unit_status` or `status`.

Unit status is instead resolved from the live canonical-unit page through the
canonical `SchedulerNotionEvidenceAdapter` / `NotionContractAdapter` pair, so
archived and human-review detection stay owned upstream. This path only maps
those canonical booleans onto the existing #973 status vocabulary.

## Activation state

The shipped catalog declares **no verified binding**: every
`verification_state` is `unverified` and every identity is `null`. Admission
therefore fails closed before any secret-bearing step, and the runner reports
`dispatch_status: "blocked"`.

Live activation requires separately authorized excluded-surface work: the
bounded workflow file, the repository secret, the read-only Notion integration,
Notion source sharing, and re-verified source identities. Historical #962
identities are planning leads only and are deliberately absent from this
executable allowlist.

## Public API

```python
from scripts.agent_os_notion_read_request import (
    admit_notion_read_request,
    load_catalog,
    run_notion_read_request,
)

evidence = run_notion_read_request(
    transport_payload,                       # governed ingress transport.json
    expected_repository="Blummer92/agent-os",
    expected_actor="Blummer92",
    generated_at="2026-09-11T18:00:00Z",     # caller-supplied; no system clock
)
```

CLI form, matching the existing ingress evidence convention:

```bash
PYTHONPATH=src:. python -m scripts.agent_os_notion_read_request.runner \
  --transport "$RUNNER_TEMP/agent-os-ingress/transport.json" \
  --repository "$GITHUB_REPOSITORY" \
  --allowed-actor Blummer92 \
  --generated-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --output "$RUNNER_TEMP/agent-os-notion-read/result.json"
```

## Sensitive-data boundary

The boundary is structural, not a natural-language phrase list:

1. Projection inputs are the repository-owned catalog and the #973 validated
   state record only. A raw Notion response is never an input.
2. Every projected object is rebuilt from a fixed key allowlist, so an unknown
   upstream field is dropped rather than published.
3. Evidence references keep `system`/`stable_id` but drop `exact_location` and
   `verification_evidence`, which can disclose private page locations.
4. A source whose declared `content_class` is not public-projectable cannot be
   registered in the catalog at all.
5. A final guard refuses any credential-class key carrying anything but a
   boolean state flag.

## Validation

```bash
PYTHONPATH=src:. python -m pytest tests/agent_os_notion_read_request -q
cd 08_Tooling/workflow-scheduler && PYTHONPATH=src python -m pytest \
  tests/test_2283_notion_read_ingress.py -q
bash 07_Agent_Tests/validate-repo-structure.sh
./scripts/validate-all.sh
```

## Rollback

Remove this package, its focused tests, its validation-profile rule, and the
`notion-read` branches in the governed ingress and the GCE adapter. No external
cleanup is required: no credential, workflow, Notion permission, or live read
is created by this package.
