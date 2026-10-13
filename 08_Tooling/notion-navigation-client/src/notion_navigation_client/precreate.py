"""Pure, advisory pre-create preflight over the cached Navigation Index (#3307).

Before an agent proposes or creates a new Notion-facing structure (a field,
dashboard, database, workflow, or prompt), `precreate_preflight` composes the
existing cached lookups into one finite, reason-coded answer to four questions:

1. Is there an exact or safely normalized existing navigation match?
2. Does the Duplicate / Drift Watchlist flag a related duplicate-risk family?
3. Which owner / source-of-truth route should be verified live next?
4. Is human review required before proceeding?

The answer is advisory evidence about a cache. It never authorizes a create,
merge, rename, retire, or schema change; `no-cached-match` is never proof that a
new structure is safe; and every result requires live Notion verification before
any downstream mutation or governed decision. Nothing here does I/O: the caller
supplies an index-like object (normally `NavigationIndex`) and, optionally, the
clock reading and freshness policy.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from .records import NAVIGATION_WARNING

PREFLIGHT_CONTRACT = "navigation-index-precreate-preflight"
PREFLIGHT_CONTRACT_VERSION = "1.0"

KIND_DASHBOARD = "dashboard"
KIND_DATABASE = "database"
KIND_FIELD = "field"
KIND_WORKFLOW = "workflow"
KIND_PROMPT = "prompt"
PREFLIGHT_KINDS = (KIND_DASHBOARD, KIND_DATABASE, KIND_FIELD, KIND_WORKFLOW, KIND_PROMPT)

OUTCOME_EXISTING_MATCH = "existing-match"
OUTCOME_DUPLICATE_RISK_REVIEW = "duplicate-risk-review"
OUTCOME_NO_CACHED_MATCH = "no-cached-match"
OUTCOME_STALE_OR_UNVERIFIED = "stale-or-unverified"
OUTCOME_MANUAL_REVIEW = "manual-review"
OUTCOMES = (
    OUTCOME_EXISTING_MATCH,
    OUTCOME_DUPLICATE_RISK_REVIEW,
    OUTCOME_NO_CACHED_MATCH,
    OUTCOME_STALE_OR_UNVERIFIED,
    OUTCOME_MANUAL_REVIEW,
)

IDENTITY_EXACT = "exact-match"
IDENTITY_NORMALIZED = "normalized-match"
IDENTITY_AMBIGUOUS = "ambiguous"
IDENTITY_UNREADABLE = "unreadable"
IDENTITY_NONE = "no-match"
IDENTITY_NOT_EVALUATED = "not-evaluated"

CURRENTNESS_WITHIN_POLICY = "within-policy"
CURRENTNESS_STALE = "stale"
CURRENTNESS_UNVERIFIED = "unverified"
CURRENTNESS_NOT_EVALUATED = "not-evaluated"

# Reason codes, in the order the phases emit them.
R_UNSUPPORTED_KIND = "request.unsupported-kind"
R_EMPTY_NAME = "request.empty-name"
R_DATABASE_REQUIRED = "request.database-required"
R_DATABASE_NOT_APPLICABLE = "request.database-not-applicable"
R_EMPTY_INFORMATION_TYPE = "request.empty-information-type"
R_IDENTITY_EXACT = "identity.exact-match"
R_IDENTITY_NORMALIZED = "identity.normalized-match"
R_IDENTITY_AMBIGUOUS = "identity.ambiguous"
R_IDENTITY_DUPLICATE_ROWS = "identity.duplicate-cache-rows"
R_IDENTITY_UNREADABLE = "identity.record-unreadable"
R_IDENTITY_NONE = "identity.no-match"
R_DUPLICATE_HIT = "duplicate-risk.watchlist-hit"
R_DUPLICATE_NONE = "duplicate-risk.no-hit"
R_REVIEW_FLAGGED = "review.record-flagged"
R_REVIEW_UNCLEAR = "review.flag-unclear"
R_CURRENT_WITHIN_POLICY = "currentness.within-policy"
R_CURRENT_STALE = "currentness.stale"
R_CURRENT_NO_POLICY = "currentness.no-freshness-policy"
R_CURRENT_NO_RECORDS = "currentness.no-refresh-records"
R_CURRENT_UNRESOLVED = "currentness.refresh-time-unresolved"
R_CURRENT_FUTURE = "currentness.refresh-time-in-future"
R_CURRENT_UNAVAILABLE = "currentness.refresh-log-unavailable"
R_CURRENT_MALFORMED = "currentness.refresh-log-malformed"
R_ROUTE_MATCHED = "routing.matched-record"
R_ROUTE_PARENT = "routing.parent-database"
R_ROUTE_PARENT_MISSING = "routing.parent-database-not-cached"
R_ROUTE_MATRIX = "routing.source-of-truth-matrix"
R_ROUTE_MATRIX_MISSING = "routing.information-type-not-cached"
R_ROUTE_NONE = "routing.none"

NEXT_STEP = {
    OUTCOME_EXISTING_MATCH: (
        "Reuse the matched structure instead of creating a new one, and verify it live in Notion "
        "before relying on it."
    ),
    OUTCOME_DUPLICATE_RISK_REVIEW: (
        "Route to human review before creating or changing anything, and verify the related "
        "structures live in Notion. Cached duplicate-risk evidence never authorizes a merge, "
        "rename, retirement, or schema change."
    ),
    OUTCOME_NO_CACHED_MATCH: (
        "The cache has no match. This is not proof that creating is safe; verify live in Notion "
        "before creating anything."
    ),
    OUTCOME_STALE_OR_UNVERIFIED: (
        "The cache's currentness could not be established, so an absence of matches proves "
        "nothing; refresh the cache or verify live in Notion before relying on any cached finding."
    ),
    OUTCOME_MANUAL_REVIEW: (
        "The request or the cached evidence is invalid or ambiguous; resolve it with a human and "
        "verify live in Notion before proceeding."
    ),
}

# Columns copied into a route as verification guidance. Only columns present in the
# cached record are copied; values are the sheet's raw strings, never interpreted.
_ROUTE_FIELDS = {
    KIND_DASHBOARD: ("Notion URL", "Notion ID", "Dashboard Type", "Owner / Source of Truth?"),
    KIND_DATABASE: (
        "Database ID",
        "Data Source ID",
        "Notion URL",
        "Source-of-Truth Role",
        "Owner Dashboard",
    ),
    KIND_FIELD: (
        "Database Name",
        "Property Name",
        "Field Name",
        "Recommended Owner",
        "Similar / Duplicate Fields",
    ),
    KIND_WORKFLOW: ("Starting Database/Dashboard", "Source of Truth", "Agents Involved"),
    KIND_PROMPT: ("Agent Type", "Notion Edit Permission?"),
    "source-of-truth": (
        "Source-of-Truth Database",
        "Source-of-Truth Dashboard",
        "Verification Step Before Editing",
    ),
}
_REVIEW_COLUMNS = ("Human Review Needed?", "Human Review Required?")


class NavigationLookup(Protocol):
    """The cached lookups the preflight composes; `NavigationIndex` satisfies this.

    An index may additionally offer `get_refresh_log(limit=...)` (#3306). When it
    does, the preflight reads it as currentness evidence; when it does not, the
    cache's currentness is reported as unverified.
    """

    def list_names(self, kind: str, database: str | None = None) -> list[str]: ...

    def get_dashboard(self, name: str) -> dict | None: ...

    def get_database(self, name: str) -> dict | None: ...

    def get_field(self, database: str, field: str) -> dict | None: ...

    def get_workflow(self, workflow_name: str) -> dict | None: ...

    def get_prompt(self, prompt_name: str) -> dict | None: ...

    def get_source_of_truth(self, information_type: str) -> dict | None: ...

    def check_duplicate_risk(self, name: str) -> list[dict]: ...


@dataclass(frozen=True)
class PreCreateRequest:
    """What the caller is about to propose or create.

    `database` is required for (and only valid with) kind `field`.
    `information_type` optionally names a Source of Truth Matrix row to route
    against when the proposed structure is not yet in the cache.
    """

    kind: str
    name: str
    database: str | None = None
    information_type: str | None = None


def normalize_name(value: str) -> str:
    """The one supported name normalization: NFKC, case-fold, collapse whitespace.

    Punctuation, hyphens, plurals, word order, abbreviations, and synonyms are
    deliberately not normalized; two names that differ in any of those do not match.
    """
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _echo(value: object) -> object:
    return value if value is None or isinstance(value, str) else f"<{type(value).__name__}>"


def _request_problems(request: PreCreateRequest) -> list[str]:
    problems: list[str] = []
    if request.kind not in PREFLIGHT_KINDS:
        problems.append(R_UNSUPPORTED_KIND)
    if _text(request.name) is None:
        problems.append(R_EMPTY_NAME)
    if request.kind == KIND_FIELD and _text(request.database) is None:
        problems.append(R_DATABASE_REQUIRED)
    if request.kind in PREFLIGHT_KINDS and request.kind != KIND_FIELD and request.database is not None:
        problems.append(R_DATABASE_NOT_APPLICABLE)
    if request.information_type is not None and _text(request.information_type) is None:
        problems.append(R_EMPTY_INFORMATION_TYPE)
    return problems


def _fetch_record(index: NavigationLookup, request: PreCreateRequest, stored_name: str) -> dict | None:
    if request.kind == KIND_DASHBOARD:
        record = index.get_dashboard(stored_name)
    elif request.kind == KIND_DATABASE:
        record = index.get_database(stored_name)
    elif request.kind == KIND_FIELD:
        record = index.get_field(request.database or "", stored_name)
    elif request.kind == KIND_WORKFLOW:
        record = index.get_workflow(stored_name)
    else:
        record = index.get_prompt(stored_name)
    return dict(record) if isinstance(record, dict) else None


def _resolve_identity(index: NavigationLookup, request: PreCreateRequest) -> dict:
    occurrences: dict[str, int] = {}
    for stored in index.list_names(request.kind, database=request.database):
        if _text(stored) is not None:
            occurrences[stored] = occurrences.get(stored, 0) + 1

    target = normalize_name(request.name)
    candidates: list[tuple[str, str]] = []
    if request.name in occurrences:
        candidates.append(("exact", request.name))
    candidates.extend(
        ("normalized", stored)
        for stored in occurrences
        if stored != request.name and normalize_name(stored) == target
    )

    matches = [
        {"basis": basis, "name": stored, "occurrences": occurrences[stored]}
        for basis, stored in candidates
    ]
    if not matches:
        return {"status": IDENTITY_NONE, "matches": [], "reason_codes": [R_IDENTITY_NONE]}

    unreadable = False
    for match in matches:
        record = _fetch_record(index, request, match["name"])
        if record is None:
            unreadable = True
        match["record"] = record

    if unreadable:
        return {"status": IDENTITY_UNREADABLE, "matches": matches, "reason_codes": [R_IDENTITY_UNREADABLE]}

    duplicated_rows = any(match["occurrences"] > 1 for match in matches)
    if len(matches) > 1 or duplicated_rows:
        codes = [R_IDENTITY_AMBIGUOUS]
        if duplicated_rows:
            codes.append(R_IDENTITY_DUPLICATE_ROWS)
        return {"status": IDENTITY_AMBIGUOUS, "matches": matches, "reason_codes": codes}

    if matches[0]["basis"] == "exact":
        return {"status": IDENTITY_EXACT, "matches": matches, "reason_codes": [R_IDENTITY_EXACT]}
    return {"status": IDENTITY_NORMALIZED, "matches": matches, "reason_codes": [R_IDENTITY_NORMALIZED]}


def _duplicate_risk(index: NavigationLookup, request: PreCreateRequest, identity: dict) -> dict:
    queries = [request.name]
    queries.extend(match["name"] for match in identity["matches"] if match["name"] not in queries)

    hits: list[dict] = []
    seen: set[str] = set()
    for query in queries:
        for record in index.check_duplicate_risk(query):
            fingerprint = repr(sorted(record.items()))
            if fingerprint not in seen:
                seen.add(fingerprint)
                hits.append({"matched_on": query, "record": dict(record)})

    return {
        "checked_names": queries,
        "hit_count": len(hits),
        "hits": hits,
        "reason_codes": [R_DUPLICATE_HIT if hits else R_DUPLICATE_NONE],
    }


def _review_state(record: dict) -> str:
    """`required`, `not-required`, or `unclear` for one cached record's review flag.

    Only an explicit "No" clears a record. A missing, blank, or unrecognized flag
    is `unclear`, and anything starting with "Yes" is `required`; both require review.
    """
    for column in _REVIEW_COLUMNS:
        if column in record:
            value = record[column]
            text = value.strip().casefold() if isinstance(value, str) else ""
            if text == "no":
                return "not-required"
            return "required" if text.startswith("yes") else "unclear"
    return "unclear"


def _route(source: str, kind: str, key: str, record: dict) -> dict:
    fields = {column: record[column] for column in _ROUTE_FIELDS[kind] if column in record}
    return {"source": source, "kind": kind, "key": key, "fields": fields}


def _routing(index: NavigationLookup, request: PreCreateRequest, identity: dict) -> tuple[dict, list[dict]]:
    routes: list[dict] = []
    codes: list[str] = []
    records: list[dict] = []

    for match in identity["matches"]:
        if match.get("record") is not None:
            routes.append(_route("matched-record", request.kind, match["name"], match["record"]))
    if routes:
        codes.append(R_ROUTE_MATCHED)

    if request.kind == KIND_FIELD:
        parent = index.get_database(request.database or "")
        if isinstance(parent, dict):
            records.append(dict(parent))
            routes.append(_route("parent-database", KIND_DATABASE, request.database or "", parent))
            codes.append(R_ROUTE_PARENT)
        else:
            codes.append(R_ROUTE_PARENT_MISSING)

    if request.information_type is not None:
        matrix = index.get_source_of_truth(request.information_type)
        if isinstance(matrix, dict):
            records.append(dict(matrix))
            routes.append(_route("source-of-truth-matrix", "source-of-truth", request.information_type, matrix))
            codes.append(R_ROUTE_MATRIX)
        else:
            codes.append(R_ROUTE_MATRIX_MISSING)

    if not routes:
        codes.append(R_ROUTE_NONE)
    return {"routes": routes, "reason_codes": codes}, records


def _parse_utc(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _currentness_verdict(status: str, code: str | None, max_age: timedelta | None, **extra: object) -> dict:
    return {
        "status": status,
        "reason_code": code,
        "latest_refresh_by_source_row": None,
        "latest_refresh_utc": None,
        "max_age_seconds": None if max_age is None else int(max_age.total_seconds()),
        "age_seconds": None,
        "detail": None,
        **extra,
    }


def _currentness(
    index: NavigationLookup, now: datetime | None, max_age: timedelta | None
) -> dict:
    """Judge cache currentness from #3306 Refresh Log evidence; never from a clock read here."""

    def verdict(status: str, code: str, **extra: object) -> dict:
        return _currentness_verdict(status, code, max_age, **extra)

    getter = getattr(index, "get_refresh_log", None)
    if getter is None:
        return verdict(CURRENTNESS_UNVERIFIED, R_CURRENT_UNAVAILABLE, detail="index-has-no-refresh-log")
    try:
        evidence = getter()
    except Exception as error:  # any probe failure is "unverified", never "fresh"
        return verdict(CURRENTNESS_UNVERIFIED, R_CURRENT_UNAVAILABLE, detail=type(error).__name__)

    latest = evidence.get("latest_observed_refresh") if isinstance(evidence, dict) else None
    total = evidence.get("total_populated_rows") if isinstance(evidence, dict) else None
    if not isinstance(latest, dict) or isinstance(total, bool) or not isinstance(total, int):
        return verdict(CURRENTNESS_UNVERIFIED, R_CURRENT_MALFORMED)
    if total == 0:
        return verdict(CURRENTNESS_UNVERIFIED, R_CURRENT_NO_RECORDS)

    positional = latest.get("by_source_row")
    summary = None
    if isinstance(positional, dict) and isinstance(positional.get("timestamp"), dict):
        summary = {
            "source_row": positional.get("source_row"),
            "raw": positional["timestamp"].get("raw"),
            "status": positional["timestamp"].get("status"),
        }

    by_timestamp = latest.get("by_timestamp")
    if by_timestamp is None:
        return verdict(
            CURRENTNESS_UNVERIFIED,
            R_CURRENT_UNRESOLVED,
            latest_refresh_by_source_row=summary,
            detail=latest.get("by_timestamp_unavailable_reason"),
        )
    instant = _parse_utc(by_timestamp.get("timestamp", {}).get("utc") if isinstance(by_timestamp, dict) else None)
    if instant is None:
        return verdict(CURRENTNESS_UNVERIFIED, R_CURRENT_MALFORMED, latest_refresh_by_source_row=summary)

    base = {"latest_refresh_by_source_row": summary, "latest_refresh_utc": by_timestamp["timestamp"]["utc"]}
    if now is None or max_age is None:
        return verdict(CURRENTNESS_UNVERIFIED, R_CURRENT_NO_POLICY, **base)
    age = now - instant
    if age < timedelta(0):
        return verdict(CURRENTNESS_UNVERIFIED, R_CURRENT_FUTURE, age_seconds=int(age.total_seconds()), **base)
    status, code = (
        (CURRENTNESS_WITHIN_POLICY, R_CURRENT_WITHIN_POLICY)
        if age <= max_age
        else (CURRENTNESS_STALE, R_CURRENT_STALE)
    )
    return verdict(status, code, age_seconds=int(age.total_seconds()), **base)


def precreate_preflight(
    index: NavigationLookup,
    request: PreCreateRequest,
    *,
    now: datetime | None = None,
    max_age: timedelta | None = None,
) -> dict:
    """Run the advisory pre-create preflight and return a JSON-serializable result.

    Outcome precedence, first rule that applies:

    1. `manual-review`: invalid request, ambiguous identity (several stored names
       normalize alike, or the cache repeats a name), or an unreadable cached record.
    2. `duplicate-risk-review`: the Duplicate / Drift Watchlist has a hit for the
       requested name or a matched stored name.
    3. `existing-match`: exactly one exact or normalized cached match.
    4. `stale-or-unverified`: nothing matched, but the cache is not shown to be
       within the caller's freshness policy, so absence proves nothing.
    5. `no-cached-match`: nothing matched in a cache shown to be within policy.

    `now` (timezone-aware) and `max_age` are the caller's freshness policy; the
    module never reads a clock. Without both, currentness is `unverified`. The
    cache is shown to be current only when the index offers `get_refresh_log`
    (#3306) and every Refresh Log row states its timezone; see `_currentness`.

    Lookup failures raised by `index` propagate; only the currentness probe is
    treated as soft evidence. Raises TypeError for a non-`PreCreateRequest` and
    ValueError for a naive `now` or a non-positive `max_age`.
    """
    if not isinstance(request, PreCreateRequest):
        raise TypeError("request must be a PreCreateRequest")
    if now is not None and (not isinstance(now, datetime) or now.tzinfo is None):
        raise ValueError("now must be a timezone-aware datetime")
    if max_age is not None and (not isinstance(max_age, timedelta) or max_age <= timedelta(0)):
        raise ValueError("max_age must be a positive timedelta")

    problems = _request_problems(request)
    if problems:
        # Nothing is looked up for an invalid request, so no section claims evidence.
        identity = {"status": IDENTITY_NOT_EVALUATED, "matches": [], "reason_codes": []}
        duplicate = {"checked_names": [], "hit_count": 0, "hits": [], "reason_codes": []}
        routing = {"routes": [], "reason_codes": []}
        currentness = _currentness_verdict(CURRENTNESS_NOT_EVALUATED, None, max_age)
        outcome = OUTCOME_MANUAL_REVIEW
        reason_codes = list(problems)
        flagged = False
    else:
        identity = _resolve_identity(index, request)
        duplicate = _duplicate_risk(index, request, identity)
        currentness = _currentness(index, now, max_age)
        routing, route_records = _routing(index, request, identity)

        consulted = [match["record"] for match in identity["matches"] if match.get("record") is not None]
        consulted += [hit["record"] for hit in duplicate["hits"]] + route_records
        states = {_review_state(record) for record in consulted}
        review_codes = [
            code
            for state, code in (("required", R_REVIEW_FLAGGED), ("unclear", R_REVIEW_UNCLEAR))
            if state in states
        ]
        flagged = bool(review_codes)

        if identity["status"] in (IDENTITY_AMBIGUOUS, IDENTITY_UNREADABLE):
            outcome = OUTCOME_MANUAL_REVIEW
        elif duplicate["hit_count"]:
            outcome = OUTCOME_DUPLICATE_RISK_REVIEW
        elif identity["status"] in (IDENTITY_EXACT, IDENTITY_NORMALIZED):
            outcome = OUTCOME_EXISTING_MATCH
        elif currentness["status"] != CURRENTNESS_WITHIN_POLICY:
            outcome = OUTCOME_STALE_OR_UNVERIFIED
        else:
            outcome = OUTCOME_NO_CACHED_MATCH
        reason_codes = [
            *identity["reason_codes"],
            *duplicate["reason_codes"],
            *review_codes,
            currentness["reason_code"],
            *routing["reason_codes"],
        ]

    return {
        "contract": PREFLIGHT_CONTRACT,
        "contract_version": PREFLIGHT_CONTRACT_VERSION,
        "outcome": outcome,
        "reason_codes": reason_codes,
        "request": {
            "kind": _echo(request.kind),
            "name": _echo(request.name),
            "database": _echo(request.database),
            "information_type": _echo(request.information_type),
        },
        "live_verification_required": True,
        "authorizes_mutation": False,
        "human_review_required": flagged
        or outcome in (OUTCOME_DUPLICATE_RISK_REVIEW, OUTCOME_MANUAL_REVIEW),
        "next_step": NEXT_STEP[outcome],
        "navigation_warning": NAVIGATION_WARNING,
        "identity": {"status": identity["status"], "matches": identity["matches"]},
        "duplicate_risk": {
            "checked_names": duplicate["checked_names"],
            "hit_count": duplicate["hit_count"],
            "hits": duplicate["hits"],
        },
        "routing": {"routes": routing["routes"]},
        "currentness": currentness,
    }
