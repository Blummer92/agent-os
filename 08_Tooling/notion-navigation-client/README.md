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

Prints the matching record(s) as JSON, including the sheet's own
`navigation_warning` and `Human Review Needed?` fields — never drop these
when relaying a result to a human or another agent.

## Tests

    pytest tests/

All tests run without live Google credentials: `records.py` and `index.py`
are tested directly (`index.py` against fixture rows in
`samples/sample_tabs.json`, transcribed from the real sheet's tabs), and
`sheets_client.py`/`cli.py` are tested against a mocked Google client.

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
