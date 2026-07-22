from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def parse_link_header(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    relations: dict[str, str] = {}
    for part in value.split(","):
        sections = [section.strip() for section in part.split(";")]
        if not sections or not sections[0].startswith("<") or not sections[0].endswith(">"):
            raise ValueError("malformed Link header")
        url = sections[0][1:-1]
        rel = None
        for section in sections[1:]:
            if section.startswith("rel="):
                rel = section[4:].strip('"')
        if not rel or rel in relations:
            raise ValueError("missing or duplicate Link relation")
        relations[rel] = url
    return relations


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
