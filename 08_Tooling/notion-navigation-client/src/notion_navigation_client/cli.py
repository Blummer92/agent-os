"""CLI: read-only lookups and Refresh Log chronology evidence from the navigation-index sheet.

No ALLOW_WRITE gate -- nothing in this package can write to the sheet or
to Notion, so there is no write path to guard.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from .index import NavigationIndex
from .precreate import (
    PREFLIGHT_KINDS,
    R_DATABASE_REQUIRED,
    PreCreateRequest,
    precreate_preflight,
    request_problems,
)
from .refresh_log import DEFAULT_LIMIT, MAX_LIMIT, validate_limit
from .sheets_client import build_sheets_service, fetch_tab_values, get_credentials

MAX_AGE_HOURS_LIMIT = 87600  # ten years; keeps the freshness policy a sane, finite timedelta

LOOKUPS = {
    "dashboard": lambda index, key, field: index.get_dashboard(key),
    "database": lambda index, key, field: index.get_database(key),
    "field": lambda index, key, field: index.get_field(key, field),
    "source-of-truth": lambda index, key, field: index.get_source_of_truth(key),
    "workflow": lambda index, key, field: index.get_workflow(key),
    "prompt": lambda index, key, field: index.get_prompt(key),
    "duplicate-risk": lambda index, key, field: index.check_duplicate_risk(key),
}


def _add_sheet_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sheet-id", default=os.environ.get("NOTION_NAV_SHEET_ID", ""))
    parser.add_argument("--client-secret", default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_PATH", ""))
    parser.add_argument("--token-path", default=os.environ.get("GOOGLE_OAUTH_TOKEN_PATH", ""))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only lookups against the Notion navigation-index sheet.")
    sub = parser.add_subparsers(dest="command", required=True)

    lookup = sub.add_parser("lookup", help="Look up one record by its key.")
    lookup.add_argument("kind", choices=sorted(LOOKUPS), help="Which tab to look up.")
    lookup.add_argument("key", help="Dashboard/Database/Information Type/Workflow/Prompt name (or Database Name for kind=field).")
    lookup.add_argument("--field", default=None, help="Field name; required for kind=field.")
    _add_sheet_arguments(lookup)

    refresh_log = sub.add_parser(
        "refresh-log",
        help=(
            "Bounded Refresh Log chronology evidence. Navigation-cache refreshes only: "
            "not a complete history of work, and never a substitute for live verification."
        ),
    )
    refresh_log.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Number of populated rows to return, counted back from the bottom of the sheet, 1-{MAX_LIMIT} (default: {DEFAULT_LIMIT}).",
    )
    _add_sheet_arguments(refresh_log)

    preflight = sub.add_parser(
        "preflight",
        help=(
            "Advisory pre-create duplicate and routing preflight over cached evidence. "
            "Never authorizes a create; live Notion verification is always still required."
        ),
    )
    preflight.add_argument("kind", choices=PREFLIGHT_KINDS, help="Kind of structure about to be proposed or created.")
    preflight.add_argument("name", help="Proposed name of the structure.")
    preflight.add_argument("--database", default=None, help="Database name; required for kind=field.")
    preflight.add_argument(
        "--information-type",
        default=None,
        help="Optional Source of Truth Matrix information type to route against.",
    )
    preflight.add_argument(
        "--max-age-hours",
        type=float,
        default=None,
        help=(
            "Freshness policy: how old the latest Refresh Log entry may be and still count as current. "
            "Without it, cache currentness is reported as unverified."
        ),
    )
    preflight.add_argument("--sheet-id", default=os.environ.get("NOTION_NAV_SHEET_ID", ""))
    preflight.add_argument("--client-secret", default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_PATH", ""))
    preflight.add_argument("--token-path", default=os.environ.get("GOOGLE_OAUTH_TOKEN_PATH", ""))

    return parser.parse_args(argv)


def _preflight_request(args: argparse.Namespace) -> PreCreateRequest:
    return PreCreateRequest(args.kind, args.name, database=args.database, information_type=args.information_type)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.sheet_id:
        print("Refusing to run: --sheet-id or NOTION_NAV_SHEET_ID is required.", file=sys.stderr)
        return 1
    if args.command == "lookup" and args.kind == "field" and not args.field:
        print("Refusing to run: --field is required for kind=field.", file=sys.stderr)
        return 1
    if args.command == "preflight":
        problems = request_problems(_preflight_request(args))
        if problems:
            hint = " --database is required for kind=field." if R_DATABASE_REQUIRED in problems else ""
            print(f"Refusing to run: invalid preflight request: {', '.join(problems)}.{hint}", file=sys.stderr)
            return 1
        # nan and inf fail the bounds comparison too; a positive value below
        # timedelta's microsecond resolution would become a zero-length policy.
        if args.max_age_hours is not None and not (
            0 < args.max_age_hours <= MAX_AGE_HOURS_LIMIT and timedelta(hours=args.max_age_hours) > timedelta(0)
        ):
            print(f"Refusing to run: --max-age-hours must be greater than 0 and at most {MAX_AGE_HOURS_LIMIT}.", file=sys.stderr)
            return 1
    if args.command == "refresh-log":
        try:
            validate_limit(args.limit)
        except ValueError:
            print(f"Refusing to run: --limit must be an integer between 1 and {MAX_LIMIT}.", file=sys.stderr)
            return 1

    credentials = get_credentials(args.client_secret, args.token_path)
    service = build_sheets_service(credentials)
    index = NavigationIndex(functools.partial(fetch_tab_values, service, args.sheet_id))

    if args.command == "preflight":
        policy = {}
        if args.max_age_hours is not None:
            policy = {"now": datetime.now(timezone.utc), "max_age": timedelta(hours=args.max_age_hours)}
        # The exit status never carries the verdict: every outcome still needs live verification.
        print(json.dumps(precreate_preflight(index, _preflight_request(args), **policy), indent=2))
        return 0

    if args.command == "refresh-log":
        # An empty log is still a successful read: the envelope reports it.
        print(json.dumps(index.get_refresh_log(args.limit), indent=2))
        return 0

    result = LOOKUPS[args.kind](index, args.key, args.field)
    print(json.dumps(result, indent=2))
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())
