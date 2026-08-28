from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlparse

from .models import TrustedRepositoryIdentity


PAGINATION_DIAGNOSTIC_KINDS = frozenset(
    {
        "pagination:link-empty",
        "pagination:link-parse",
        "pagination:next-scheme",
        "pagination:next-host",
        "pagination:next-path",
        "pagination:next-page-missing",
        "pagination:next-page-invalid",
        "pagination:next-page-ambiguous",
        "pagination:next-page-non-advancing",
        "pagination:next-per-page-invalid",
        "pagination:next-per-page-ambiguous",
        "pagination:next-per-page-changed",
        "pagination:next-state-ambiguous",
        "pagination:next-state-changed",
        "pagination:unexpected",
    }
)

_MAX_REPOSITORY_ID_DIGITS = 20
_MAX_QUERY_FIELDS = 3
_MAX_QUERY_INTEGER_DIGITS = 10
_REGISTERED_RELATION_RE = re.compile(r"[A-Za-z][A-Za-z0-9.-]*\Z")
_CANONICAL_POSITIVE_INTEGER_RE = re.compile(r"[1-9][0-9]*\Z", re.ASCII)
_LINK_RE = re.compile(r"\s*<([^>]*)>\s*(?:;\s*(.*))?\s*")
_PARAM_RE = re.compile(
    r"([a-zA-Z0-9!#$%&\'*+\-.^_`|~]+)\s*=\s*(?:([^\",;]+)|\"((?:[^\"\\]|\\.)*)\")"
)


class PaginationDiagnosticError(ValueError):
    """Fail-closed pagination error carrying one fixed internal identifier."""

    def __init__(self, kind: str, message: str) -> None:
        if kind not in PAGINATION_DIAGNOSTIC_KINDS:
            raise ValueError("unknown pagination diagnostic kind")
        super().__init__(message)
        self.kind = kind


def _fail(kind: str, message: str) -> None:
    raise PaginationDiagnosticError(kind, message)


def _normalize_relation(relation: str) -> str:
    if _REGISTERED_RELATION_RE.fullmatch(relation):
        return relation.lower()
    return relation


def _split_parameters(value: str) -> list[str]:
    parameters: list[str] = []
    current: list[str] = []
    in_quotes = False
    escaped = False

    for char in value:
        if in_quotes:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_quotes = False
            continue

        if char == '"':
            in_quotes = True
            current.append(char)
        elif char == ";":
            parameter = "".join(current).strip()
            if not parameter:
                _fail("pagination:link-parse", "malformed Link parameter")
            parameters.append(parameter)
            current = []
        else:
            current.append(char)

    if in_quotes:
        _fail("pagination:link-parse", "malformed Link parameter")

    parameter = "".join(current).strip()
    if not parameter:
        _fail("pagination:link-parse", "malformed Link parameter")
    parameters.append(parameter)
    return parameters


def parse_link_header(value: str | None) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, str):
        raise TypeError("Link header must be a string or None")
    if not value.strip():
        _fail("pagination:link-empty", "Link header is present but empty")

    relations: dict[str, str] = {}

    for part in _split_links(value):
        match = _LINK_RE.fullmatch(part)
        if not match:
            _fail("pagination:link-parse", "malformed Link header")

        url, params_str = match.groups()
        if not params_str:
            _fail("pagination:link-parse", "missing Link relation")

        rel_values: list[str] = []
        rel_parameter_count = 0
        for parameter in _split_parameters(params_str):
            param_match = _PARAM_RE.fullmatch(parameter)
            if not param_match:
                _fail("pagination:link-parse", "malformed Link parameter")
            name, token_val, quoted_val = param_match.groups()
            if name.lower() != "rel":
                continue
            rel_parameter_count += 1
            if rel_parameter_count > 1:
                _fail("pagination:link-parse", "duplicate Link rel parameter")
            rel_val = token_val if token_val is not None else quoted_val
            if not rel_val:
                _fail("pagination:link-parse", "missing Link relation")
            rel_values.extend(rel_val.split())

        if rel_parameter_count != 1 or not rel_values:
            _fail("pagination:link-parse", "missing Link relation")

        for relation in rel_values:
            normalized_relation = _normalize_relation(relation)
            if normalized_relation in relations:
                _fail(
                    "pagination:link-parse",
                    "duplicate or ambiguous Link relation",
                )
            relations[normalized_relation] = url

    return relations


def _split_links(value: str) -> list[str]:
    links: list[str] = []
    current: list[str] = []
    in_quotes = False
    in_uri = False
    escaped = False

    for char in value:
        if in_quotes:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_quotes = False
            continue

        if in_uri:
            current.append(char)
            if char == "<":
                _fail("pagination:link-parse", "malformed Link header")
            if char == ">":
                in_uri = False
            continue

        if char == '"':
            in_quotes = True
            current.append(char)
        elif char == "<":
            in_uri = True
            current.append(char)
        elif char == ">":
            _fail("pagination:link-parse", "malformed Link header")
        elif char == ",":
            part = "".join(current).strip()
            if not part:
                _fail("pagination:link-parse", "malformed Link header")
            links.append(part)
            current = []
        else:
            current.append(char)

    if in_quotes or in_uri:
        _fail("pagination:link-parse", "malformed Link header")

    part = "".join(current).strip()
    if not part:
        _fail("pagination:link-parse", "malformed Link header")
    links.append(part)
    return links


def _query_values(query: str) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    if not query:
        return {}, {}

    raw_fields = query.split("&")
    if len(raw_fields) > _MAX_QUERY_FIELDS or any(not field for field in raw_fields):
        _fail("pagination:link-parse", "malformed or excessive next-link query")

    try:
        parsed_fields = parse_qsl(
            query,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=_MAX_QUERY_FIELDS,
        )
    except ValueError as error:
        raise PaginationDiagnosticError(
            "pagination:link-parse", "malformed or excessive next-link query"
        ) from error

    if len(parsed_fields) != len(raw_fields):
        _fail("pagination:link-parse", "malformed next-link query")

    values: dict[str, list[str]] = {}
    raw_values: dict[str, list[str]] = {}
    allowed_names = {"page", "per_page", "state"}

    for raw_field, (name, value) in zip(raw_fields, parsed_fields):
        raw_name, separator, raw_value = raw_field.partition("=")
        if not separator or name not in allowed_names:
            _fail("pagination:link-parse", "unexpected next-link query parameter")
        if not raw_name:
            _fail("pagination:link-parse", "malformed next-link query parameter")
        values.setdefault(name, []).append(value)
        raw_values.setdefault(name, []).append(raw_value)

    return values, raw_values


def _parse_canonical_positive_integer(raw_value: str, *, kind: str, message: str) -> int:
    if (
        len(raw_value) > _MAX_QUERY_INTEGER_DIGITS
        or _CANONICAL_POSITIVE_INTEGER_RE.fullmatch(raw_value) is None
    ):
        _fail(kind, message)
    return int(raw_value)


def _validate_repository_path(
    path: str,
    *,
    repository: str,
    trusted_repository_identity: TrustedRepositoryIdentity | None,
) -> None:
    named_path = f"/repos/{repository}/issues"
    if path == named_path:
        return

    numeric_match = re.fullmatch(
        rf"/repositories/([1-9][0-9]{{0,{_MAX_REPOSITORY_ID_DIGITS - 1}}})/issues",
        path,
    )
    if numeric_match is None:
        _fail("pagination:next-path", "next link changed repository or endpoint")

    if (
        trusted_repository_identity is None
        or trusted_repository_identity.repository_key != repository.lower()
        or trusted_repository_identity.repository_id != int(numeric_match.group(1))
    ):
        _fail("pagination:next-path", "next link repository identity is unverified")


def validated_next_page(
    link_header: str | None,
    *,
    repository: str,
    current_page: int,
    per_page: int,
    state: str,
    trusted_repository_identity: TrustedRepositoryIdentity | None = None,
) -> tuple[int | None, bool]:
    relations = parse_link_header(link_header)
    next_url = relations.get("next")
    if next_url is None:
        terminal_proven = (link_header is not None) or (current_page == 1)
        return None, terminal_proven

    parsed = urlparse(next_url)
    if parsed.scheme != "https":
        _fail("pagination:next-scheme", "next link must use HTTPS")
    if parsed.netloc != "api.github.com":
        _fail("pagination:next-host", "next link changed the API authority")
    if parsed.fragment:
        _fail("pagination:link-parse", "next link must not contain a fragment")

    _validate_repository_path(
        parsed.path,
        repository=repository,
        trusted_repository_identity=trusted_repository_identity,
    )

    query, raw_query = _query_values(parsed.query)
    page_values = query.get("page")
    if page_values is None:
        _fail("pagination:next-page-missing", "next link is missing page")
    if len(page_values) != 1:
        _fail("pagination:next-page-ambiguous", "next link has multiple page values")
    page = _parse_canonical_positive_integer(
        raw_query["page"][0],
        kind="pagination:next-page-invalid",
        message="next link has invalid page",
    )
    if page <= current_page:
        _fail("pagination:next-page-non-advancing", "next link does not advance")

    linked_per_page_values = query.get("per_page")
    if linked_per_page_values is not None:
        if len(linked_per_page_values) != 1:
            _fail(
                "pagination:next-per-page-ambiguous",
                "next link has multiple per_page values",
            )
        linked_per_page_value = linked_per_page_values[0]
        if linked_per_page_value:
            linked_per_page = _parse_canonical_positive_integer(
                raw_query["per_page"][0],
                kind="pagination:next-per-page-invalid",
                message="next link has invalid per_page",
            )
            if linked_per_page != per_page:
                _fail(
                    "pagination:next-per-page-changed",
                    "next link changed the requested page size",
                )

    linked_state_values = query.get("state")
    if linked_state_values is not None:
        if len(linked_state_values) != 1:
            _fail(
                "pagination:next-state-ambiguous",
                "next link has multiple state values",
            )
        linked_state = linked_state_values[0]
        if linked_state and linked_state != state:
            _fail(
                "pagination:next-state-changed",
                "next link changed the requested state",
            )

    return page, False
