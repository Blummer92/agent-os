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
- Refresh Log chronology (see below) is evidence about when the cached index was
  refreshed, nothing more. It is not a complete history of teacher work, GitHub
  work, or Notion edits, and it never replaces live Notion or GitHub verification.
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

## Refresh Log chronology

`NavigationIndex.get_refresh_log(limit=20)` (CLI: `refresh-log [--limit N]`)
returns bounded, read-only evidence from the sheet's `Refresh Log` tab: when the
cached navigation index says it was refreshed from Notion, and in what order. It
uses the same read-only tab fetch and per-session cache as every other lookup;
there is no second reader, history store, scheduler, or currentness service.

What the result is, and is not:

- It is navigation-cache evidence. Every result carries the sheet's
  `navigation_warning` (and so does every entry) plus a `completeness_notice`:
  the Refresh Log is **not** a complete history of teacher work, GitHub work, or
  Notion edits, and it is never a substitute for live Notion or GitHub
  verification.
- It answers "when does the sheet say it was last refreshed?" and "which refresh
  record came before another?". It does not say anything about the current state
  of Notion.

Abridged result (values are illustrative):

    {
      "tab": "Refresh Log",
      "navigation_warning": "Navigation aid only. Verify live state in Notion ...",
      "completeness_notice": "Refresh Log rows describe navigation-cache refreshes only ...",
      "ordering": "source-row",
      "window": "last-populated-source-rows",
      "limit": 20,
      "total_populated_rows": 3,
      "returned_rows": 3,
      "truncated": false,
      "rows_with_cells_outside_header": 0,
      "timestamp_column": "Refresh Date",
      "timestamp_column_present": true,
      "timestamp_status_counts": {"explicit-utc": 1, "explicit-offset": 0, "ambiguous-timezone": 0,
                                  "unrecognized-format": 2, "missing": 0},
      "source_order_matches_timestamp_order": null,
      "latest_observed_refresh": {
        "by_source_row": {"source_row": 5, "timestamp": {"raw": "8/9/2026 16:37:20",
                          "status": "unrecognized-format", "utc": null}, "record": {...}, "navigation_warning": "..."},
        "by_timestamp": null,
        "by_timestamp_unavailable_reason": "timestamps-not-all-explicit",
        "agree": null
      },
      "entries": [{"source_row": 3, "timestamp": {"raw": "2026-07-04 16:04 UTC", "status": "explicit-utc",
                   "utc": "2026-07-04T16:04:00Z"}, "record": {...}, "navigation_warning": "..."}, ...]
    }

Rules:

- **Bounded.** `entries` holds at most `limit` rows (1-200, default 20): the last
  populated rows in source-row order. `total_populated_rows`, `returned_rows`, and
  `truncated` say what the window leaves out. The summary fields
  (`timestamp_status_counts`, `latest_observed_refresh`, ...) always cover every
  populated row on the tab, not only the window. An out-of-range `limit` raises
  `ValueError`; the CLI refuses it before any credential is loaded.
- **Source order and raw values.** Entries are never re-sorted. `source_row` is the
  1-based row on the sheet (row 1 is the warning banner and row 2 the header on
  the live tab, so the first data row is 3); blank rows are skipped but keep the
  numbering. `record` holds the cells under the header's columns exactly as read,
  keyed by the live header names (`Refresh Date`, `Script Version`, `Refreshed By`,
  `Data Sources Scanned`, `Dashboards Scanned`, `Properties Scanned`,
  `Relations Found`, `Errors`, `Unresolved Questions`, `Notes`), so the
  human-review and currentness columns (`Errors`, `Unresolved Questions`, `Notes`)
  pass through untouched. As on every other tab, short rows are padded with `""`
  and a repeated header name keeps only its last column. Only the header's columns
  decide whether a row is populated; rows with content past the last header column
  are counted in `rows_with_cells_outside_header` (that content is not kept).
- **No timezone guessing.** `timestamp.raw` is the cell text, preserved
  byte-for-byte. `timestamp.utc` is set only when that text states its own zone:
  `UTC`, `Z`, or a numeric offset within +/-14:00. `timestamp.status` is one of
  `explicit-utc`, `explicit-offset`, `ambiguous-timezone` (an ISO-like date and
  time with no zone: left unresolved), `unrecognized-format` (anything else,
  including date-only values, locale formats such as `8/9/2026`, and abbreviations
  such as `PST`), or `missing`.
- **Two answers for "latest", never merged.** `latest_observed_refresh.by_source_row`
  is the last populated row; it presumes nothing about whether the sheet is kept
  oldest-first. `by_timestamp` is the row with the greatest UTC instant, produced
  only when every populated row has explicit zone evidence (one unresolved row
  could be the newest); otherwise it is `null` and
  `by_timestamp_unavailable_reason` says why (`no-entries`,
  `timestamp-column-missing`, `timestamps-not-all-explicit`). `agree` reports
  whether both name the same row, and `source_order_matches_timestamp_order`
  reports whether the sheet is oldest-first when that is provable (`null`
  otherwise). Callers that need ordering between two entries parse and compare
  `timestamp.utc` when both are present (it is ISO-8601 whose fractional-second
  precision varies, so do not compare the strings) and otherwise fall back to
  `source_row` while treating the order as unverified.

Observed shape of the live tab (an export read on 2026-10-13): row 1 is the
warning banner, row 2 is the header above, the first data row's `Refresh Date` is
a string that states `UTC`, and later rows are datetime cells formatted
`m/d/yyyy h:mm:ss` with no zone (displayed like `8/9/2026 16:10:03`). Those are
reported as `unrecognized-format`: day/month order is locale-dependent and no zone
is stated, so nothing is guessed. Against that shape `by_timestamp` is unavailable
and `by_source_row` is the answer.

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
    python -m notion_navigation_client.cli refresh-log --limit 5

Prints the matching record(s) as JSON, including the sheet's own
`navigation_warning` and `Human Review Needed?` fields — never drop these
when relaying a result to a human or another agent.

`refresh-log` prints the Refresh Log chronology evidence described above and exits
`0` whenever the tab was read, including for an empty log (the JSON reports it).
Keep its `navigation_warning` and `completeness_notice` when relaying it.

## Tests

    pytest tests/

All tests run without live Google credentials: `records.py`, `refresh_log.py`,
and `index.py` are tested directly (`index.py` against fixture rows in
`samples/sample_tabs.json`, transcribed from the real sheet's tabs; the
`Refresh Log` fixture keeps the live banner row, header names, and the cells'
displayed timestamp formats but uses sanitized values), and
`sheets_client.py`/`cli.py` are tested against a mocked Google client.
`tests/test_refresh_log.py` also pins the read-only surface: the OAuth scope stays
`spreadsheets.readonly`, no known Sheets write method appears in the package's
code, and the Sheets `values()` resource is only ever read with `.get(...)`.
`precreate.py` is tested directly as well; its tests also pin that the module is
pure (no I/O or network imports) and that no outcome authorizes a mutation, and
three of them exercise the preflight against the real
`NavigationIndex.get_refresh_log` in the live display shape.

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
- Refresh Log timestamps that carry no zone stay unresolved (`ambiguous-timezone`
  for ISO-like text, `unrecognized-format` for the live tab's `m/d/yyyy h:mm:ss`
  display). The sheet's own timezone setting is not read and no zone or day/month
  order is assumed, so `by_timestamp` stays unavailable until every row states its
  zone in an ISO-like form. The fixture's strings for those cells follow the
  sheet's number format; the exact text the Sheets API returns for them has not
  been observed live.
- The Refresh Log is read as a whole tab (one cached read, like every other tab);
  `limit` bounds what is returned, not what is fetched.
- The pre-create preflight inherits `check_duplicate_risk`'s matching limits: it also reports
  names that only appear inside a Watchlist family description, and it cannot see duplicates the Watchlist does not
  list. It judges cache currentness only from the Refresh Log; against the live tab's
  current shape (a UTC-stamped first row, later datetime cells formatted as
  `m/d/yyyy h:mm:ss` with no zone) that evidence is
  unresolved, so a "no match" there is reported as `stale-or-unverified`.
