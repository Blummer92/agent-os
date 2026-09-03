# Notion Compute Decision Writer

Bounded, offline-first repository contract for Issue #1424.

Consumes an already-computed and already-serialized #1419 compute-control
projection payload (schema `agent-os-compute-control-projection/1.0`, itself
built on the #1097 Coding Command Center handoff) and prepares one bounded
update plan for an existing Notion `Tasks / Issues` record. The only writable
field is `Compute Decision`; `Source Link` is the identity anchor and is
never rewritten.

It does not calculate compute readiness, authorization, validation, routing,
or currentness. Those remain owned by #1097/#1419 and their upstream
sources; this package only projects an already-derived disposition into the
approved Notion destination.

## Boundary

- No Notion SDK, credentials, or network access; `dry_run=True` by default
  and makes zero client calls.
- Non-dry execution requires an injected `NotionComputeDecisionClient`
  supplied by a separately authorized runtime; live mutation remains
  approval-gated under the #1420 Change Request.
- The #1419 `ComputeControlProjection` dataclass is deliberately not
  imported. Its serialized payload is consumed by schema reference only
  (`schema_name`/`schema_version` pinned), keeping this package
  dependency-free and matching #1419's own choice to mirror the
  validation-head vocabulary by reference rather than import it.
- `NotionComputeDecisionClient` mirrors the #959
  `visual_asset_notion_writer.NotionClient` read/write shape for this
  destination only. It is a distinct, narrowly-scoped Protocol, not a shared
  abstraction: no second Notion client implementation, credential path, or
  synchronization service is introduced.
- Frozen destination: data source `5216eacf-639d-4881-92bc-a634ead56669`
  (the #1420 live target inspection). A request naming any other data source
  fails closed as a precheck failure.
- Target resolution uses only the exact `Source Link` property value; a
  title-only match never resolves a target. Zero exact matches is a
  fail-closed `notion-compute-decision-target-missing` -- a new row is never
  created. More than one exact match is
  `notion-compute-decision-target-ambiguous`.
- A projection whose own #1419 reason codes signal fail-closed currentness,
  or whose repository/issue/head identity does not match the caller's
  freshly reacquired `CanonicalIdentity`, is blocked before any target
  resolution or write is attempted.
- Every `ComputeDisposition` value maps deterministically to one #1420
  presentation string, including `unavailable` -> `"Verify Current State"`,
  which is itself the fail-closed display value (never a false-green state).
- Only `Compute Decision` is ever named in an `update_page` call; every
  other property on the row is left untouched by construction.
- Already-matching values return `UNCHANGED_SKIP`; no mutation is issued.
- A transient/rate-limited update outcome is never blindly retried: the page
  is read back and only classified as `UPDATED` if the readback already
  shows the intended value, otherwise `AMBIGUOUS_WRITE_RESULT`.
- Successful updates require exact page readback of identity and the
  intended value before being reported as verified.
- Planning is a pure function of its inputs: identical evidence always
  produces an identical plan.

## Dry-run example

```python
from notion_compute_decision_writer import (
    CanonicalIdentity,
    ComputeDecisionWriteRequest,
    DATA_SOURCE_ID,
    PropertyBinding,
    parse_compute_control_projection_evidence,
    plan_and_write_compute_decision,
)

projection = parse_compute_control_projection_evidence({
    "schema_name": "agent-os-compute-control-projection",
    "schema_version": "1.0",
    "repository": "Blummer92/agent-os",
    "issue_number": 1424,
    "current_head_sha": "a" * 40,
    "compute_disposition": "run-now",
    "reason_codes": ["compute.profile-static"],
})

request = ComputeDecisionWriteRequest(
    data_source_id=DATA_SOURCE_ID,
    source_link="https://github.com/Blummer92/agent-os/issues/1424",
    source_link_property_name="Source Link",
    expected_identity=CanonicalIdentity("Blummer92/agent-os", 1424, "a" * 40),
    projection=projection,
    compute_decision_binding=PropertyBinding("compute_decision", "Compute Decision", "rich_text"),
)
result = plan_and_write_compute_decision(request)  # DRY_RUN; zero Notion calls
```

## Tests

Run `PYTHONPATH=src pytest -q` from this package directory. The focused
suite uses an injected in-memory fake client and covers exact-identity target
resolution, title-only-match insufficiency, ambiguous/missing targets,
stale/conflicting #1419 evidence, the full disposition-to-presentation
mapping, unchanged-skip, unrelated-property preservation, the field
allowlist, ambiguous-write reconciliation without blind retry, readback
mismatch, and determinism.

Live Notion adapter implementation, credentials, live pilots, schema
mutation, and production activation remain outside #1424's offline
repository implementation and are owned by the separately approved #1420
Change Request.
