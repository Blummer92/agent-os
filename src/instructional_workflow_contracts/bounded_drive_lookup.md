# Bounded Drive lookup for the Teacher-Directed Revision Lane

Issue #2745 binds a provider-thin bounded target-lookup contract to the
Teacher-Directed Revision Lane. The repository module imports no Google
SDK and performs no live connector call by itself.

## Why it exists

On 2026-09-21 a teacher-directed worksheet revision
("Update the worksheet to match that decision. Keep everything else the
same.") acknowledged the plan, then froze indefinitely in a Google Drive
search: the UI stayed on "Searching Drive for Photography Co..." with an
opaque Thinking state. The requested revision never reached a completed
artifact or a visible governed blocker. A teacher-directed revision must
always terminate in either a completed artifact or an explicit, visible
governed blocker — never a silent freeze.

## Contract

`resolve_revision_target` accepts an injected host `DriveLookupClient`
(`search_files` / `get_file_metadata`) plus the teacher's revision scope
(`changed_sections`, `preserved_sections`), and returns exactly one
terminal `BoundedLookupResult`:

| Disposition | Meaning | Host behavior |
|---|---|---|
| `RESOLVED` | Exact target identity established. | Continue automatically into the authorized bounded revision. |
| `AMBIGUOUS` | Several candidates. | Fail visibly; ask only for the smallest necessary target clarification (candidate names are supplied). |
| `NOT_FOUND` | No candidate. | Fail visibly with the target/access blocker; keep the resumable handoff. |
| `LOOKUP_TIMEOUT` | Attempt cap or elapsed budget exhausted. | Fail visibly; keep the resumable handoff; do not retry silently. |
| `LOOKUP_ERROR` | Provider failure or invalid contract input. | Fail visibly with the preserved failure detail; keep the resumable handoff. |

## Bounds (repository-owned)

- Attempt cap: `MAX_LOOKUP_ATTEMPTS = 3`.
- Elapsed budget: `MAX_LOOKUP_SECONDS = 60.0` checked between attempts with an injectable clock.
- Scope limits: title hint capped at `MAX_TITLE_HINT_CHARS = 80` characters; page size `LOOKUP_PAGE_SIZE = 10`; candidates capped at `MAX_CANDIDATES = 10`; query restricted to Google Docs MIME type and `trashed = false`.
- Exact identity reuse: when `exact_drive_id` is already known (for example from prior conversation evidence), it is verified directly — no broad title search is performed (issue acceptance criterion).

## Host responsibilities

Each provider call must be per-call timeout-bounded by the host connector,
surfacing `TimeoutError` on expiry; the contract converts that into a
visible `LOOKUP_TIMEOUT` blocker. A provider call that never returns is a
host contract violation, not a permitted state.

## Failure surfacing

Every non-resolved disposition carries:

- a teacher-visible blocker message (`user_visible_message`) naming the
  target/access/capability failure precisely;
- a read-only resumable handoff preserving the teacher's revision request
  (`changed_sections`, `preserved_sections`), reason codes, failure
  detail, candidates, and a resume instruction (re-run with
  `exact_drive_id` to continue without broad-searching again).

No external write is performed or authorized; the handoff's authority
block is all-false.

## Authorization

Repository implementation and tests are Tier 1 / `external_write: false`.
Tests use injected fakes and zero credentials/network. The host's use of
this contract does not grant Drive mutation authority; the teacher-directed
revision lane's existing write-authorization rules still govern any edit.
