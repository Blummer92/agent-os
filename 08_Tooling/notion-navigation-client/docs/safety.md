# Safety Boundaries

This tool only ever reads. `sheets_client.py` exposes exactly one call,
`fetch_tab_values`, using the `spreadsheets.readonly` OAuth scope — there is
no update, append, or batchUpdate method anywhere in this package, so it is
structurally impossible for it to write to the navigation sheet.

A lookup result is never authorization to write to Notion or to the sheet.
See `01_Shared_Standards/notion/notion-navigation-index-standard.md` for the
two-step pattern (navigation index first, live Notion verification before
any write or governed-field decision) and
`01_Shared_Standards/google-workspace/` for the underlying Workspace
read-only default this tool follows.
