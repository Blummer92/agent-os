from __future__ import annotations

import pytest
from scripts.agent_os_github_issue_provider.pagination import (
    parse_link_header,
    validated_next_page,
)

def test_parse_link_header_valid():
    header = '<https://api.github.com/repos/owner/repo/issues?page=2>; rel="next", <https://api.github.com/repos/owner/repo/issues?page=5>; rel="last"'
    parsed = parse_link_header(header)
    assert parsed["next"] == "https://api.github.com/repos/owner/repo/issues?page=2"
    assert parsed["last"] == "https://api.github.com/repos/owner/repo/issues?page=5"

def test_parse_link_header_comma_in_quotes():
    header = '<https://example.com>; rel="next", <https://example.com/2>; rel="something,else"'
    parsed = parse_link_header(header)
    assert parsed["next"] == "https://example.com"
    assert parsed["something,else"] == "https://example.com/2"

def test_parse_link_header_multiple_rels():
    header = '<https://example.com>; rel="next last"'
    parsed = parse_link_header(header)
    assert parsed["next"] == "https://example.com"
    assert parsed["last"] == "https://example.com"

def test_parse_link_header_empty():
    assert parse_link_header("") == {}
    assert parse_link_header(None) == {}

def test_parse_link_header_malformed():
    with pytest.raises(ValueError, match="malformed Link header"):
        parse_link_header("not a link")
    
    # Missing angle brackets
    with pytest.raises(ValueError, match="malformed Link header"):
        parse_link_header("http://example.com; rel=next")

def test_parse_link_header_duplicate_or_ambiguous():
    # Duplicate rel across entries
    header = '<https://ex.com/1>; rel="next", <https://ex.com/2>; rel="next"'
    with pytest.raises(ValueError, match="duplicate or ambiguous Link relation"):
        parse_link_header(header)
    
    # Duplicate rel within one entry
    header = '<https://ex.com/1>; rel="next next"'
    with pytest.raises(ValueError, match="duplicate or ambiguous Link relation"):
        parse_link_header(header)

def test_parse_link_header_missing_rel():
    # Entirely missing rel
    header = '<https://example.com>; title="Something"'
    with pytest.raises(ValueError, match="missing or duplicate Link relation"):
        parse_link_header(header)
    
    # Empty rel
    header = '<https://example.com>; rel=""'
    with pytest.raises(ValueError, match="missing or duplicate Link relation"):
        parse_link_header(header)

def test_validated_next_page_valid():
    header = '<https://api.github.com/repos/owner/repo/issues?page=2&per_page=100&state=open>; rel="next"'
    next_page, terminal_proven = validated_next_page(
        header,
        repository="owner/repo",
        current_page=1,
        per_page=100,
        state="open",
    )
    assert next_page == 2
    assert terminal_proven is False

def test_validated_next_page_none():
    next_page, terminal_proven = validated_next_page(None, repository="a/b", current_page=1, per_page=10, state="o")
    assert next_page is None
    assert terminal_proven is True

    next_page, terminal_proven = validated_next_page(None, repository="a/b", current_page=2, per_page=10, state="o")
    assert next_page is None
    assert terminal_proven is False

    header = '<https://api.github.com/repos/owner/repo/issues?page=5>; rel="last"'
    next_page, terminal_proven = validated_next_page(header, repository="owner/repo", current_page=1, per_page=100, state="open")
    assert next_page is None
    assert terminal_proven is True

def test_validated_next_page_wrong_host():
    header = '<https://api.evil.com/repos/owner/repo/issues?page=2&per_page=100&state=open>; rel="next"'
    with pytest.raises(ValueError, match="next link must target api.github.com"):
        validated_next_page(header, repository="owner/repo", current_page=1, per_page=100, state="open")

def test_validated_next_page_wrong_repository():
    header = '<https://api.github.com/repos/other/repo/issues?page=2&per_page=100&state=open>; rel="next"'
    with pytest.raises(ValueError, match="next link changed repository or endpoint"):
        validated_next_page(header, repository="owner/repo", current_page=1, per_page=100, state="open")

def test_validated_next_page_does_not_advance():
    header = '<https://api.github.com/repos/owner/repo/issues?page=1&per_page=100&state=open>; rel="next"'
    with pytest.raises(ValueError, match="next link does not advance"):
        validated_next_page(header, repository="owner/repo", current_page=1, per_page=100, state="open")

def test_validated_next_page_changed_query():
    header = '<https://api.github.com/repos/owner/repo/issues?page=2&per_page=50&state=open>; rel="next"'
    with pytest.raises(ValueError, match="next link changed the requested query"):
        validated_next_page(header, repository="owner/repo", current_page=1, per_page=100, state="open")
    
    header = '<https://api.github.com/repos/owner/repo/issues?page=2&per_page=100&state=closed>; rel="next"'
    with pytest.raises(ValueError, match="next link changed the requested query"):
        validated_next_page(header, repository="owner/repo", current_page=1, per_page=100, state="open")
