# #2283 GitHub-Controlled Notion Read Path

## Status

Implementation contract and current state for issue #2283. The repository owner
decided on 2026-09-11 that sanitized curriculum and Visual Asset Library results
may be returned through the public `Blummer92/agent-os` GitHub surface, and that
no private transport repository is introduced.

That decision does **not** permit credentials, API headers, sensitive
student/private information, unrestricted raw Notion payloads, or secret-derived
diagnostics to become public.

The repository-side implementation is complete and validated. Live activation
remains blocked on separately authorized excluded surfaces (see below).

## Target architecture

```text
ChatGPT
-> GitHub MCP
-> bounded `/agent-os notion-read <request-id>` issue comment
-> existing governed issue_comment admission
-> GitHub Actions standard hosted runner
-> existing #936 read-only Notion adapter
-> sanitized bounded result on the public GitHub evidence surface
-> ChatGPT reads the result through GitHub MCP
```

GitHub remains the Agent OS governance/control surface. Notion remains the
teacher-planning/current-curriculum and Visual Asset Library working source.
Public GitHub result evidence is a request-scoped projection, not a second
curriculum or asset source of truth.

## Implemented surfaces

| Surface | Location |
| --- | --- |
| finite `notion-read` command shape and transport admission | `08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/github_issue_comment_ingress.py` |
| explicit refusal to route a notion-read into the GCE control path | `08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/gce_gcloud_adapter.py` |
| request catalog, admission, execution seam, public projection, runner | `scripts/agent_os_notion_read_request/` |
| focused security and regression tests | `tests/agent_os_notion_read_request/`, `08_Tooling/workflow-scheduler/tests/test_2283_notion_read_ingress.py` |

## Reused capabilities

No second curriculum system is created. The path composes existing behavior:

- the existing governed `issue_comment` admission pattern;
- #936 read-only Notion adapter semantics and the `NOTION_TOKEN` contract;
- #980 request-sensitive curriculum read planning;
- #975 provider-neutral evidence assembly;
- #973 currentness/conflict/authority resolution;
- #971 relation-first Visual Asset Library retrieval;
- #2282 execution-surface routing and the read-only action bound.

## Request admission

The executable comment carries only a finite repository-owned slug:

```text
/agent-os notion-read photography-foundations-visual-assets
```

Before any secret-bearing or network step, admission validates the canonical
repository, the trusted actor, the expected event, the expected issue target,
run-attempt/replay constraints, the finite command shape, the request identity,
the allowed request class, and every approved source binding. Only then is
`secret_dispatch_authorized` true.

Arbitrary URLs, arbitrary Notion ids (including a bare UUID, which otherwise
satisfies the slug grammar), arbitrary shell syntax, arbitrary HTTP methods,
arbitrary API paths, arbitrary property names, arbitrary filters, workspace-wide
search, extra executable tokens, and free-form teacher text all fail closed.

Request classes map onto existing #980 intent: `canonical-unit`,
`current-curriculum`, `visual-assets`, `teacher-modeling`, `packet-materials`.

## Read-only boundary

Only `get_page` and `query_data_source` are reachable, reusing the #2282
allowlist. That bound is imported from #2282 rather than restated, and it is
re-asserted on this path's own executor because the #936 adapter's action
surface is wider than #2282's (it also exposes page-body and page-property
reads, which this path must never reach). No create, update, archive, delete,
comment, share, schema mutation, bulk synchronization, or workspace-wide crawl
path exists. Every data-source read is pinned to one approved binding and
bounded to a single page of results.

## Ownership boundary for the repository catalog

`notion_read_catalog.json` owns binding and policy configuration only: request
ids, provider identity bindings, the finite request-class vocabulary, the
publication content class, and operator-controlled verification state.

It must never own curriculum semantic truth. A repository-declared canonical
unit status would decide #973's disposition from configuration and would make
its non-active-unit protection unreachable, so catalog loading rejects any
declared `unit_status`/`status`. Unit status is resolved from the live
canonical-unit read through the canonical normalizer instead, which means the
path reads the canonical unit page twice: once to resolve live status, then
again as #980's own plan step, which re-verifies identity independently.

## Visual Asset Library boundary

Retrieval stays relation-first through the governed `Canonical Unit` relation.
Titles, filenames, prompts, notes, and keyword similarity cannot substitute for
that relation: an asset without the relation is dropped by #975 regardless of
how well it matches. Asset existence never becomes approved use or production
authority.

## Result projection

The public result is derived only from the repository-owned catalog and the #973
validated state record. A raw Notion response is never a projection input, so
raw page bodies, private property values, and workspace dumps cannot reach the
public surface.

The projection carries request id, request class, canonical unit identity,
provider-neutral source identity, source revision/currentness, provenance,
semantic/value owner class, bounded curriculum evidence, bounded asset metadata,
approved-use/reuse/human-review evidence, explicit missing/stale/conflicting/
inaccessible state, `write_allowed=false`, `production_authorized=false`, and a
generated timestamp.

Sanitization is structural rather than a natural-language phrase list: fixed key
allowlists, declared source content classes, dropped private page locations, and
a guard refusing any credential-class key that carries anything but a boolean.

## Cost boundary

Routine reads require no persistent GCE and no larger paid runner. The path
targets a standard GitHub-hosted runner, which current GitHub billing
documentation states is free for public repositories. `Blummer92/agent-os` is
currently public. Repository-visibility or billing-policy drift is a
re-evaluation trigger before continued activation.

## Current activation state

`notion_read_catalog.json` ships with **no verified binding**: every
`verification_state` is `unverified` and every source and canonical unit identity
is `null`. Admission therefore fails closed with `canonical-unit-unverified`
before any secret-bearing step, and the runner reports `dispatch_status:
"blocked"`.

Historical #962 identities are planning leads only and are deliberately absent
from the executable allowlist, so a stale lead can never be dispatched.

## Remaining excluded-surface authorization packet

Live activation requires the repository owner to separately authorize:

1. **Workflow file.** A bounded `notion_read` job in
   `.github/workflows/agent-os-governed-invocation.yml` (or a sibling workflow),
   gated on `github.event.issue.pull_request == null`, running the existing
   ingress parser and then
   `python -m scripts.agent_os_notion_read_request.runner`, publishing the result
   JSON with `actions/upload-artifact` and a bounded job summary.
   The job must supply the read executor **through this package's seam**, which
   applies the inherited #2282 action bound. It must not call
   `NotionReadOnlyAdapter` directly: that adapter's action surface is wider than
   #2282's, so a direct binding would be a second, unbounded provider path.
2. **Workflow permissions.** `permissions: contents: read` only. No
   `issues: write`, `pull-requests: write`, `contents: write`, `actions: write`,
   or `id-token: write` is required for this job.
3. **Repository secret.** One secret named `NOTION_TOKEN`, exposed only to the
   admitted dispatch step. The value never appears in code, comments, logs,
   summaries, artifacts, fixtures, or ChatGPT.
4. **Notion principal.** One existing read-only Notion integration, reused
   rather than duplicated. No write capability, no workspace-wide access.
5. **Notion source sharing.** Share only the Canonical Digital Media Unit
   Registry and the Visual Asset Library with that integration.
6. **Verified source identities.** Re-verify those two data-source ids and the
   Photography Foundations canonical unit page id live, then set them in
   `notion_read_catalog.json` with `verification_state: "verified-current"`.
7. **Bounded live smoke test.** One `visual-assets` request for Photography
   Foundations, proving canonical-unit resolution plus relation-first asset
   retrieval.

No other request class is activated by this packet: the wider classes stay
fail-closed on `source-not-allowlisted` until their sources are separately
verified.

## Rollback

Remove the workflow job, revoke the Notion integration token, remove its source
sharing, reset the catalog bindings to `unverified`/`null`, and stop producing
request-scoped result artifacts. Optionally remove
`scripts/agent_os_notion_read_request/`, its tests, its validation-profile rule,
and the `notion-read` branches in the ingress and GCE adapter.

No canonical curriculum or asset data requires rollback: Notion remains the
working source and GitHub stores only bounded request-scoped evidence.
