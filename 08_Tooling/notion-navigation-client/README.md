# Notion Navigation Client

Read-only client for the Notion navigation-index Google Sheet: a cache of
Notion dashboard/database ownership, schema, routing, and duplicate-risk
data, refreshed on demand by a separate Apps Script that scans live Notion.
Agents call this client for fast owner/routing/duplicate-risk lookups
instead of a live Notion call or re-deriving the same answer each time.

This package is the Notion-specific read client / adapter for the cached Notion navigation index. It is not the full cross-system Navigation Registry. Cross-system Navigation Registry governance lives in `01_Shared_Standards/navigation/navigation-registry-standard.md` and is owned by the Integration Manager; the Notion-specific cache standard lives in `01_Shared_Standards/notion/notion-navigation-index-standard.md`.

## Safety

- Read-only end to end: `sheets_client.py` exposes only one call
  (`fetch_tab_values`, scope `spreadsheets.readonly`) — no write method
  exists anywhere in this package.
- This client reads cached Notion navigation-index tabs only. It does not read
  or verify live Notion state by itself.
- A lookup result is never authorization to write to Notion, change readiness
  or status, change ownership, make source-of-truth decisions, change source
  authority, authorize production, change sharing, or edit governed fields.
- Agents must verify live Notion before any write, readiness/status change,
  ownership change, source-of-truth decision, or governed-field decision.
- Preserve returned `navigation_warning` values and any human-review flags
  when relaying a lookup result to a human or another agent.
- See `docs/safety.md`, `docs/registry-fit.md`,
  `01_Shared_Standards/navigation/navigation-registry-standard.md`, and
  `01_Shared_Standards/notion/notion-navigation-index-standard.md`.

## Live sheet compatibility

The client supports tabs where row 1 is the standard navigation warning banner
and row 2 is the header row. It also remains compatible with older fixture-style
tabs where row 1 is already the header row.

`Property Dictionary` lookups accept both live sheet terminology
(`Property Name`) and older fixture/docs terminology (`Field Name`) while keeping
the public lookup shape as `lookup field <database> --field <name>`.

## Pre-create preflight

`precreate_preflight(index, PreCreateRequest(kind, name, database=None, information_type=None))`
(CLI: `preflight KIND NAME [--database DB] [--information-type TYPE] [--max-age-hours N]`)
is the advisory check to run **before proposing or creating** a new Notion-facing
field, dashboard, database, workflow, or prompt. It composes the lookups this
package already has (`list_names`, the keyed getters, `check_duplicate_risk`, and
`get_refresh_log` when the index offers it); there is no second registry, cache,
client, or deduplication system, and it performs no I/O of its own.

It answers four questions about the **cached** index: is there an exact or safely
normalized existing match; does the Duplicate / Drift Watchlist flag a related
duplicate-risk family; which owner or source-of-truth route should be verified live
next; and is human review required. It never decides that two live Notion
properties are duplicates and never authorizes a create, merge, rename, retirement,
or schema change.

Finite outcomes, in the order the first applicable rule wins:

| Outcome | When | What the caller does |
|---|---|---|
| `manual-review` | The request is invalid; the identity is ambiguous (several stored names normalize alike, or the cache repeats a name); a field's parent database is ambiguous or not in the cached Database Registry, so the field cannot be scoped; the `information_type` is ambiguous; or a listed record cannot be read | Resolve with a human |
| `duplicate-risk-review` | The Watchlist has a hit for the requested name or a matched stored name | Human review; never clean up automatically |
| `existing-match` | Exactly one exact or normalized match | Reuse it; verify it live |
| `stale-or-unverified` | No match, and the cache is not shown to be within the caller's freshness policy | Refresh or verify live; an absence proves nothing |
| `no-cached-match` | No match in a cache shown to be within the freshness policy | Still verify live |

Every result, whatever the outcome, carries `live_verification_required: true` and
`authorizes_mutation: false`, the sheet's `navigation_warning`, the matched and
Watchlist records exactly as the sheet holds them (including `Human Review Needed?`),
a fixed `next_step` sentence, and `reason_codes` in a fixed order. The CLI exits `0`
whenever the preflight ran: the exit status never carries the verdict, because no
verdict means "safe". In particular, **`no-cached-match` is not proof that creating
is safe.**

Rules:

- **Normalization is explicit and small.** A name matches exactly, or after Unicode
  NFKC folding, case-folding, and collapsing whitespace runs. Punctuation, hyphens,
  plurals, word order, abbreviations, and synonyms are not normalized, and there is no
  fuzzy, semantic, or substring identity matching. A normalized match is reported with
  `basis: "normalized"` and the stored name it matched. The same rule resolves a
  field's parent database against the Database Registry (`identity.parent_database`),
  the optional `information_type` against the Source of Truth Matrix, and Watchlist
  Suspect names; a normalized resolution is reported with its own reason code, and an
  ambiguous one is `manual-review`. A field whose parent database is not in the cached
  Database Registry cannot be scoped, so its identity is `scope-unresolved` and the
  outcome is `manual-review` (`identity.parent-database-not-cached`).
- **Duplicate-risk evidence is the existing `check_duplicate_risk`** (exact match on
  the Suspect column, case-sensitive substring match on Similar To), asked for the
  requested name, each matched stored name, and each Watchlist Suspect name that
  normalizes like one of them. Every hit counts whatever its
  `Status`. Because Similar To is matched by substring, a name that merely appears inside
  a family description (for example a database name) is also reported.
- **Review.** Only an explicit `No` in `Human Review Needed?` (or `Human Review Required?`
  on prompts) clears a consulted record; `Yes...`, blank, missing, or any other value
  requires review (`review.record-flagged` / `review.flag-unclear`).
- **Routing is guidance only.** `routing.routes` lists where to verify live next: the
  matched record, the parent database of a field, and the Source of Truth Matrix row for
  an optional `information_type`, each with the sheet's raw routing columns and its
  `Human Review Needed?` value (a flagged route requires review too). It grants
  no write, readiness, or approval authority.
- **Currentness comes from the Refresh Log (#3306), judged by the caller's policy.** The
  module never reads a clock. The caller passes `now` (timezone-aware) and `max_age`
  (`--max-age-hours` on the CLI; the repository defines no default policy). The cache
  counts as `within-policy` only when the index offers `get_refresh_log`, every Refresh
  Log row states its timezone, and the latest refresh is no older than `max_age`.
  Otherwise currentness is `stale` or `unverified` with one reason code
  (`currentness.refresh-log-unavailable`, `.no-refresh-records`, `.refresh-time-unresolved`,
  `.no-freshness-policy`, `.refresh-time-in-future`, `.refresh-log-malformed`, `.stale`).
  The raw latest Refresh Log row stays visible. A stale or unverified cache never hides a
  finding: it only keeps "no match" from being read as meaningful.
- **Boundaries.** GitHub bug-issue duplicate and root-cause admission (#2660) is a
  different seam and is untouched. Nothing here writes to Sheets, Notion, or Drive.

## Installation

    pip install -e .

## Setup

1. Create a Google Cloud project and OAuth client credentials (Desktop app
   type), download the client secret JSON.
2. Copy `.env.example` to `.env` and fill in
   `GOOGLE_OAUTH_CLIENT_SECRET_PATH`, `GOOGLE_OAUTH_TOKEN_PATH`, and
   `NOTION_NAV_SHEET_ID` (defaults to the sheet this tool was built
   against).

## Usage

    python -m notion_navigation_client.cli lookup dashboard "Curriculum Source Control"
    python -m notion_navigation_client.cli lookup field "DM Units" --field "Generation Gate"
    python -m notion_navigation_client.cli lookup duplicate-risk "Readiness"
    python -m notion_navigation_client.cli preflight dashboard "Brand New Dashboard" --max-age-hours 24
    python -m notion_navigation_client.cli preflight field "Lesson Tag" --database "DM Units"

Prints the matching record(s) as JSON, including the sheet's own
`navigation_warning` and `Human Review Needed?` fields — never drop these
when relaying a result to a human or another agent.

## Tests

    pytest tests/

All tests run without live Google credentials: `records.py`, `precreate.py`, and
`index.py` are tested directly (`index.py` against fixture rows in
`samples/sample_tabs.json`, transcribed from the real sheet's tabs), and
`sheets_client.py`/`cli.py` are tested against a mocked Google client. The
`precreate.py` tests also pin that the module is pure (no I/O or network imports)
and that no outcome authorizes a mutation. Three tests that exercise the preflight
against the real `NavigationIndex.get_refresh_log` are skipped until that method exists.

## Limitations

- **Not tested against a live Sheets account in this session** — no Google
  credentials were available. The unit test suite runs against fixture data
  and mocked clients; the operator must supply their own OAuth credentials
  and validate the live path (`fetch_tab_values` against the real sheet)
  themselves. This package's OAuth flow (`sheets_client.get_credentials`)
  needs interactive browser consent and cannot run in this remote,
  non-interactive session — it must be run locally by the operator.
- **Live-sheet structural validation was separately attempted and is
  blocked by a platform-side connector bug, not a credentials or sharing
  issue.** A Claude.ai Google Drive connector was used to try reading the
  sheet directly to check whether its tabs/columns still match
  `samples/sample_tabs.json`. Every call (`read_file_content`,
  `list_recent_files`) failed identically with `MCP tool call requires
  approval` across org-level approval, per-chat enablement, and a fresh
  session with both confirmed on — ruling out sharing permissions, the
  file ID, and the specific tool called. Until resolved (or run locally),
  tab/column drift versus `samples/sample_tabs.json` is unverified.
- Tab and column names are matched literally against the sheet's current
  headers; if a tab is renamed or a column is added/removed in Notion's
  live schema (via the Apps Script refresh), the corresponding lookup
  method's key fields may need updating.
- `check_duplicate_risk` does simple exact/substring matching, not fuzzy
  matching — near-miss names won't surface automatically.
- The pre-create preflight inherits `check_duplicate_risk`'s matching limits: it also reports
  names that only appear inside a Watchlist family description, and it cannot see duplicates the Watchlist does not
  list. It judges cache currentness only from the Refresh Log; against the live tab's
  current shape (a UTC-stamped first row, later datetime cells formatted as
  `m/d/yyyy h:mm:ss` with no zone) that evidence is
  unresolved, so a "no match" there is reported as `stale-or-unverified`.
