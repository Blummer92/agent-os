from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


def parse_link_header(value: str | None) -> dict[str, str]:
    if not value:
        return {}

    # RFC 8288 robust parsing: <URL>; param="value", <URL>; param="value"
    # This regex identifies the main Link-Value components (URL and params block)
    # while correctly ignoring commas inside quotes.
    # Note: This parser assumes the common case where URLs are in angle brackets
    # and relations are provided via the 'rel' parameter.
    link_regex = re.compile(r'\s*<([^>]*)>\s*(?:;\s*(.*))?')
    param_regex = re.compile(r'([a-zA-Z0-9!#$%&\'*+\-.^_`|~]+)\s*=\s*(?:([^",;]+)|"([^"]*)")')

    relations: dict[str, str] = {}

    for part in _split_links(value):
        match = link_regex.match(part)
        if not match:
            raise ValueError("malformed Link header")

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
                    # RFC 8288 allows space-separated relations in rel="next prev"
                    for rel in rel_val.split():
                        if rel in relations:
                            raise ValueError("duplicate or ambiguous Link relation")
                        relations[rel] = url
        
        if not rel_found:
            raise ValueError("missing or duplicate Link relation")

    return relations


def _split_links(value: str) -> list[str]:
    # Split by commas that are NOT inside double quotes.
    links = []
    current = []
    in_quotes = False
    for char in value:
        if char == '"':
            in_quotes = not in_quotes
        elif char == ',' and not in_quotes:
            links.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if current:
        links.append("".join(current).strip())
    return links


def validated_next_page(
    link_header: str | None,
    *,
    repository: str,
    current_page: int,
    per_page: int,
    state: str,
) -> tuple[int | None, bool]:
    relations = parse_link_header(link_header)
    next_url = relations.get("next")
    if next_url is None:
        # If there is a link header but no next relation, it is proven terminal.
        # If there is NO link header on the first page, it means the result set
        # is not paginated (single page), which is also proven terminal.
        terminal_proven = (link_header is not None) or (current_page == 1)
        return None, terminal_proven

    parsed = urlparse(next_url)
    if parsed.scheme != "https" or parsed.netloc != "api.github.com":
        raise ValueError("next link must target api.github.com")
    expected_path = f"/repos/{repository}/issues"
    if parsed.path != expected_path:
        raise ValueError("next link changed repository or endpoint")
    query = parse_qs(parsed.query)
    try:
        page = int(query["page"][0])
        linked_per_page = int(query["per_page"][0])
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError("next link is missing pagination parameters") from error
    if page <= current_page:
        raise ValueError("next link does not advance")
    if linked_per_page != per_page or query.get("state", [None])[0] != state:
        raise ValueError("next link changed the requested query")
    return page, False
