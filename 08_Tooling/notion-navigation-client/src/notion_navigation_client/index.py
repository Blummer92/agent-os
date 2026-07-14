"""In-memory, per-session cache over the navigation-index tabs.

Each tab is fetched at most once per NavigationIndex instance (one Sheets
API read per tab per agent session), then parsed and looked up locally.
"""
from __future__ import annotations

from typing import Callable

from .records import index_by, rows_to_records, split_header_and_data, with_warning

TAB_DASHBOARD_REGISTRY = "Dashboard Registry"
TAB_DATABASE_REGISTRY = "Database Registry"
TAB_PROPERTY_DICTIONARY = "Property Dictionary"
TAB_SOURCE_OF_TRUTH_MATRIX = "Source of Truth Matrix"
TAB_WORKFLOW_MAP = "Workflow Map"
TAB_AGENT_PROMPT_LIBRARY = "Agent Prompt Library"
TAB_DUPLICATE_DRIFT_WATCHLIST = "Duplicate / Drift Watchlist"

_PROPERTY_DATABASE_FIELD = "Database Name"
_PROPERTY_NAME_FIELDS = ("Field Name", "Property Name")


def _property_name(record: dict) -> str:
    """Return the field/property display name from supported header variants."""
    for key in _PROPERTY_NAME_FIELDS:
        if record.get(key):
            return record[key]
    return ""


class NavigationIndex:
    """Read-only, cached lookups over the navigation-index sheet.

    `fetch_tab` must be a callable(tab_name: str) -> list[list[str]],
    e.g. `functools.partial(fetch_tab_values, service, spreadsheet_id)`.
    """

    def __init__(self, fetch_tab: Callable[[str], list[list[str]]]):
        self._fetch_tab = fetch_tab
        self._tab_cache: dict[str, list[dict]] = {}

    def _records(self, tab_name: str) -> list[dict]:
        if tab_name not in self._tab_cache:
            rows = self._fetch_tab(tab_name)
            header, data = split_header_and_data(rows)
            self._tab_cache[tab_name] = rows_to_records(header, data)
        return self._tab_cache[tab_name]

    def get_dashboard(self, name: str) -> dict | None:
        index = index_by(self._records(TAB_DASHBOARD_REGISTRY), "Dashboard Name")
        return with_warning(index.get(name))

    def get_database(self, name: str) -> dict | None:
        index = index_by(self._records(TAB_DATABASE_REGISTRY), "Database Name")
        return with_warning(index.get(name))

    def get_field(self, database: str, field: str) -> dict | None:
        records = self._records(TAB_PROPERTY_DICTIONARY)
        for record in records:
            if record.get(_PROPERTY_DATABASE_FIELD) == database and _property_name(record) == field:
                return with_warning(record)
        return None

    def get_source_of_truth(self, information_type: str) -> dict | None:
        index = index_by(self._records(TAB_SOURCE_OF_TRUTH_MATRIX), "Information Type")
        return with_warning(index.get(information_type))

    def get_workflow(self, workflow_name: str) -> dict | None:
        index = index_by(self._records(TAB_WORKFLOW_MAP), "Workflow Name")
        return with_warning(index.get(workflow_name))

    def get_prompt(self, prompt_name: str) -> dict | None:
        index = index_by(self._records(TAB_AGENT_PROMPT_LIBRARY), "Prompt Name")
        return with_warning(index.get(prompt_name))

    def check_duplicate_risk(self, name: str) -> list[dict]:
        """Exact or substring match against Suspect and Similar To columns."""
        matches = []
        for record in self._records(TAB_DUPLICATE_DRIFT_WATCHLIST):
            suspect = record.get("Suspect Field, Database, or Dashboard", "")
            similar_to = record.get("Similar To", "")
            if name == suspect or name in similar_to:
                matches.append(with_warning(record))
        return matches
