# Writer-side CKR2 relevance qualification (Draft, #3417 / #4026)

The existing governed Notion writer can persist a valid reviewed catalog entry and verify it with canonical readback, but **persistence is not proof that a future task will find the lesson**. The writer's descriptive properties are projected by CKR11 into a coarse CKR2 vocabulary. A broad `Area` or `Learning Type` can produce false positives while a specific task mechanism remains unmatched.

`scripts/agent_os_notion_lessons_write/relevance_qualification.py` is a **pre-publication review helper**, not a new Notion writer or matcher. For a reviewed **create** catalog entry it synthesizes a local Notion property readback from the exact existing writer fields, passes that shape through the **existing CKR11 normalizer**, and runs the **canonical CKR2 selector** against bounded typed positive and unrelated hard-negative task requests. It refuses missing descriptive metadata, negative false positives, positive no-matches, or positives supported only by generic CKR2 capability/classification matches. The only accepted positive selection bases are canonical contextual mechanisms (`verified-ckr6-mutation-context-match`, `pr-refresh-reconciliation-text-match`, or `exact-library-match`); these are algorithmic review evidence, **not** independent semantic proof. Ordinary broad `failure-avoidance` positives no longer qualify by themselves.

The synthetic Notion Status and Surface Before Work flag are solely for exercising the normalization/selection algorithm; they do **not** imply that a live Notion page has those protected fields, or grant publication, activation, workflow or CKR6 admission authority. Review evidence cannot establish live source currentness or semantic truth. A qualified result means only that these explicit scenarios behaved as expected against this isolated candidate, not that the real live corpus will rank it in the top three. Existing reviewed entries remain unchanged, and this helper is **not wired into the live owner-triggered writer**, because the repository has no approved persistent representation or independently established test cases for every historical entry.

Before using this helper to qualify a new lesson: obtain reviewed issue/PR provenance; author the four finite narratives plus `Area`, `Learning Type`, and `Source Link`; define representative positive and hard-negative typed task signals; execute the review using the in-repository memory-context-manager source on the Python path; inspect false-positive and miss reason codes. For every reviewed case, anchor the incident and fix to the exact source and reviewed catalog revision; use positives describing the distinctive engineering mechanism and hard negatives deliberately sharing broad categories (packaging, generic testing, Notion readback, PR refresh, host continuation). **Do not infer applicability from a single generic-positive selection.** If a relevant task cannot match under the current controlled schema, stop for a source-reviewed contract/metadata repair under #4026 rather than force a lesson ID or inject generic keywords. A source/version-bound reviewed manifest remains a separate admission prerequisite proposal; this helper neither creates nor approves one. Then use the existing owner-authorized write/readback process and independently evaluate actual CKR6 selection.

Focused command (repo root):

```sh
python -m pytest tests/agent_os_notion_lessons_write/test_relevance_qualification.py -q
```

Not in this PR: catalog auto-generation, a new Notion schema or capability property, protected activation changes, new write endpoints, automatic publication, generic prose matching, runtime CKR2 policy changes, or proof of native host consumption.


## 2026-11-23 QA hardening

- The reviewer checks scenario container types before using `len()`, returning `bounded-review-scenarios-required` for malformed inputs rather than an accidental Python exception.
- The canonical catalog validator checks collection item types before deduplication so unhashable or invalid members receive the existing finite rejection; the offline projection still never coerces `None` into a valid-looking Notion value.
- Positive selections must carry a distinct canonical contextual basis to qualify; generic `keyword-overlap` and `ecosystem-capability-match` alone return `positive-relevance-basis-unverified`. A positive hit remains counted separately from contextual qualification. All negative matches remain blockers.
- The pytest CKR2 import path is owned by the writer test package's `conftest.py` rather than the individual relevance test module. Actual source package installation, not mock selectors, is required for repository CI.
- Existing independent CKR6 manual-review decisions and Notion write/activation restrictions are unchanged.

## Notion write durability and lost-response recovery (2026-11-23)

This PR also hardens the existing **owner-admitted** live writer. A successful Notion POST/PATCH and a successfully received HTTP response are different events: the remote write may commit before the response is lost. A timeout is never permission to repeat a mutation.

- Before create: verify the fixed data-source binding, live property schema/options and the absence of an exact-title entry; use the existing bounded one-page query with `has_more == false`.
- Issue **at most one** POST/PATCH per admitted attempt. GitHub Actions serializes this destination and disallows rerun admission. No retries, fallback POSTs, or new writable fields are introduced.
- When a create response is missing or malformed, perform **one bounded exact-title reconciliation**. The query must return exactly one valid canonical page in the expected data source. Never use its mere presence to claim success.
- Fetch the recovered page directly, check all the reviewed properties, require the canonical parent and identity, then perform the existing **independent second read-only GET** with exactly matched lesson ID and revision before the runner returns success.
- If a query is empty, incomplete, ambiguous, stale, or unavailable, or if either readback mismatches, return `uncertain` with `write_attempts=1`. **Do not issue a second write**. A later manually admitted attempt must reconcile current canonical state first.
- `create_receipt_recovered=true` reports how the page identity was obtained; it does **not** claim that the current run caused the resulting state. The independent verifier explicitly reports `write_causality_established=false`.

This protects state confirmation and prevents immediate automatic duplicate POSTs. It **cannot** establish exactly-once delivery across independent attempts during Notion eventual-consistency windows without a durable, provider-enforced idempotency key or other approved write identity. If an uncertain result remains, inspect the canonical Notion data source rather than mechanically resubmitting a create.

The writer remains independent of the offline CKR2 relevance advisory. The new recovery path does not activate lessons, turn a review into write authority, or establish live lesson discoverability. The only successful run status after a write remains a result confirmed by the independent read-only observer.

Focused regression command from repository root:

```sh
python -m pytest tests/agent_os_notion_lessons_write/test_writer.py tests/agent_os_notion_lessons_write/test_live.py -q
```


## Structural-only QA fixtures versus semantic review

For shape checks, use the finite schema only: `{target_lesson_id: str | None, properties: mapping}`. Creates require every key in `NARRATIVE_TYPES`; updates allow a nonempty writable subset. Optional descriptive fields and their constraints come from `DESCRIPTIVE_TYPES`, `MAX_APPLIES_TO`, `MAX_SUPPORTING_REFS`, and the canonical repository-only source-link validators. `PROTECTED_FIELDS` must never appear in a reviewed write. The catalog definitions, not a duplicated text summary, remain the authoritative contract.

In the test suite, `structural_entry()` uses one-character, nonblank narrative placeholders for **catalog validation only**; it is never passed off as proof that a lesson is relevant to a task. CKR2/CKR11 positive and hard-negative evaluations keep mechanism-bearing reviewed text and real typed requests. Thus compact external schema summaries do not leak or overfit narrative prose, but also cannot substitute for semantic applicability or Notion persistence evidence.


## Durable create-once reservation against delayed Notion index visibility

A Notion data-source title query is not a transactional uniqueness constraint.
Even when every POST is followed by canonical GET1/GET2, a first POST can commit,
lose its response, and remain invisible to a later request's query. PR #4101
now prevents the **second POST**, not just an automatic retry in the first run.

At the create mutation boundary, after canonical owner admission, source/schema
checks and exact-title reconciliation, the live writer calls
`LiveLessonsClient.reserve_create(request_id)`. That operation performs one
authenticated, atomic `POST /repos/Blummer92/agent-os/git/refs` to create an
immutable, create-only Git tag reference under
`refs/tags/agent-os-notion-create-once-v1/<sha256>`. The digest is calculated
from the NFKC-normalized, trimmed, casefolded reviewed lesson title, so separate
reviewed request IDs with the same title share the same reservation. No lesson
prose, credentials, or arbitrary user URL appears in the ref or receipt.

The GitHub Actions workflow grants `contents: write` only to the trusted
owner-admitted job; `GITHUB_TOKEN` is passed only to the secret-bearing execute
step, not the initial admission step. The GitHub API **create-ref** operation
must succeed with a matching 201 receipt before the first Notion POST is
permitted. The live Notion client additionally requires its own reservation
flag and **consumes that flag immediately before issuing the POST**, so even
a repeated direct `LiveLessonsClient.create()` on the same instance cannot
reuse an acquired claim. There is no check-then-create race, GitHub-ref retry,
or automatic ref deletion. A duplicate (422), authorization/transport failure, or missing
receipt fails closed with **zero Notion mutations**. Git ref creation itself
is an external side effect, not an activation or Notion mutation.

This is an **at-most-once create-attempt guarantee** under the trust assumption
that the GitHub reservation refs are not deleted or modified by an authorized
repository administrator. It addresses the precise delayed-index sequence:
the first response can be lost and the Notion lookup empty, but any second
owner-authorized create for that title cannot acquire the permanent ref and
therefore cannot issue a duplicate POST. It does **not** promise at-least-once
delivery or that every attempted write is persisted: if the Git ref is committed
but the Notion POST fails (or never starts), future creates are still blocked.
That is deliberate safety-over-liveness behavior. On uncertain outcomes,
inspect Notion and the permanent GitHub reservation; **do not delete/rearm the
tag or silently resubmit**. Any manual recovery/rearm requires separate,
governed authorization and independent destination evidence.

Updates retain their distinct exact-`Lesson ID` / owner-bound revision rules
and do not acquire create reservations. Reconciliation of an already-existing
identical canonical lesson returns `unchanged` without creating a new ref.
Existing readback, independent verifier and CKR2 relevance guarantees are not
broadened by this one-shot reservation. The GitHub tag is a reservation claim,
not proof that Notion accepted a write; publication/activation remains forbidden
without the independent canonical readback and existing governance.

Offline regression tests: `tests/agent_os_notion_lessons_write/test_create_reservation.py`
exercise a create-only Git ref API double with concurrent contenders, duplicate
claims, lost reservation receipts, missing credentials, separate reviewed IDs
with equivalent titles, and the delayed-Notion-index two-owner-request sequence.
Actual GitHub tag creation and live Notion behavior have not been exercised by
these offline tests.
