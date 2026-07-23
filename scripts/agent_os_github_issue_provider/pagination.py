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


class PaginationDiagnosticError(ValueError):
    """Fail-closed pagination error carrying one fixed internal identifier."""

    def __init__(self, kind: str, message: str) -> None:
        if kind not in PAGINATION_DIAGNOSTIC_KINDS:
            raise ValueError("unknown pagination diagnostic kind")
        super().__init__(message)
        self.kind = kind


def _fail(kind: str, message: str) -> None:
    raise PaginationDiagnosticError(kind, message)


def parse_link_header(value: str | None) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, str):
        raise TypeError("Link header must be a string or None")
    if not value.strip():
        _fail("pagination:link-empty", "Link header is present but empty")

    # RFC 8288 robust parsing: <URL>; param="value", <URL>; param="value"
    # Split only on delimiters outside quoted strings and angle-bracket URIs.
    link_regex = re.compile(r"\s*<([^>]*)>\s*(?:;\s*(.*))?\s*")
    param_regex = re.compile(
        r"([a-zA-Z0-9!#$%&\'*+\-.^_`|~]+)\s*=\s*(?:([^\",;]+)|\"([^\"]*)\")"
    )

    relations: dict[str, str] = {}

    for part in _split_links(value):
        match = link_regex.fullmatch(part)
        if not match:
            _fail("pagination:link-parse", "malformed Link header")

        url, params_str = match.groups()
        rel_found = False
        if params_str:
            for param_match in param_regex.finditer(params_str):
                name, token_val, quoted_val = param_match.groups()
                if name.lower() == "rel":
                    rel_val = token_val or quoted_val
                    if not rel_val:
                        continue
                    rel_found = True
                    # RFC 8288 allows space-separated relations in rel="next prev".
                    for rel in rel_val.split():
                        if rel in relations:
                            _fail(
                                "pagination:link-parse",
                                "duplicate or ambiguous Link relation",
                            )
                        relations[rel] = url
        if not rel_found:
            _fail("pagination:link-parse", "missing Link relation")

    return relations


def _split_links(value: str) -> list[str]:
    """Split Link values only at top-level commas.

    Quoted parameter strings and angle-bracket URI references may legally contain
    commas. Malformed quote or angle-bracket state fails closed.
    """

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


def _query_values(query: str) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for name, value in parse_qsl(query, keep_blank_values=True):
        values.setdefault(name, []).append(value)
    return values


def _validate_repository_path(
    path: str,
    *,
    repository: str,
    trusted_repository_identity: TrustedRepositoryIdentity | None,
) -> None:
    named_path = f"/repos/{repository}/issues"
    if path == named_path:
        return

    numeric_match = re.fullmatch(r"/repositories/([1-9][0-9]*)/issues", path)
    if numeric_match is None:
        _fail("pagination:next-path", "next link changed repository or endpoint")

    if (
        trusted_repository_identity is None
        or trusted_repository_identity.repository != repository
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
        # A non-empty Link without next proves terminal. No Link on page one means
        # the result set fits on one page. Later pages still require explicit proof.
        terminal_proven = (link_header is not None) or (current_page == 1)
        return None, terminal_proven

    parsed = urlparse(next_url)
    if parsed.scheme != "https":
        _fail("pagination:next-scheme", "next link must use HTTPS")
    if parsed.netloc != "api.github.com":
        _fail("pagination:next-host", "next link changed the API authority")

    _validate_repository_path(
        parsed.path,
        repository=repository,
        trusted_repository_identity=trusted_repository_identity,
    )

    query = _query_values(parsed.query)
    page_values = query.get("page")
    if page_values is None:
        _fail("pagination:next-page-missing", "next link is missing page")
    if len(page_values) != 1:
        _fail("pagination:next-page-ambiguous", "next link has multiple page values")
    try:
        page = int(page_values[0])
    except (TypeError, ValueError) as error:
        raise PaginationDiagnosticError(
            "pagination:next-page-invalid", "next link has invalid page"
        ) from error
    if page <= current_page:
        _fail("pagination:next-page-non-advancing", "next link does not advance")

    # GitHub may omit trusted request parameters. Omission is safe because the
    # provider constructs the following request from the original arguments. If
    # GitHub includes state or per_page, ambiguity and drift still fail closed.
    linked_per_page_values = query.get("per_page")
    if linked_per_page_values is not None:
        if len(linked_per_page_values) != 1:
            _fail(
                "pagination:next-per-page-ambiguous",
                "next link has multiple per_page values",
            )
        linked_per_page_value = linked_per_page_values[0]
        if linked_per_page_value:
            try:
                linked_per_page = int(linked_per_page_value)
            except (TypeError, ValueError) as error:
                raise PaginationDiagnosticError(
                    "pagination:next-per-page-invalid",
                    "next link has invalid per_page",
                ) from error
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
