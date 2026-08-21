from __future__ import annotations

import re

from .models import LinkedIssueCandidate, LinkedIssueParseResult, LinkedIssueParseStatus

_SUPPORTED_KEYWORDS = r"close[sd]?|fix(?:e[sd])?|resolve[sd]?"
_CANONICAL_REPOSITORY = "blummer92/agent-os"
_REPOSITORY = r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
_SHORT_TARGET = rf"(?:(?P<repository>{_REPOSITORY}))?#(?P<number>\d+)"
_URL_TARGET = rf"https://github\.com/(?P<url_repository>{_REPOSITORY})/issues/(?P<url_number>\d+)"
_TARGET = rf"(?P<target>(?:{_URL_TARGET}|{_SHORT_TARGET}))"

EXPLICIT_LINK_RE = re.compile(rf"\b(?P<keyword>{_SUPPORTED_KEYWORDS})(?:\s*:\s*|\s+){_TARGET}\b", re.IGNORECASE)
UNSUPPORTED_LINK_RE = re.compile(rf"\b(?P<keyword>address(?:es|ed)?)(?:\s*:\s*|\s+){_TARGET}\b", re.IGNORECASE)
ISSUE_REFERENCE_RE = re.compile(rf"(?<![A-Za-z0-9_.-]){_TARGET}\b")
_AUTHORITATIVE_PREFIX_RE = re.compile(rf"\b(?P<keyword>{_SUPPORTED_KEYWORDS}|address(?:es|ed)?)\b[^#\n]{{0,80}}$", re.IGNORECASE)
_INLINE_CODE_RE = re.compile(r"`+[^`\n]*?`+")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

REQUIRED_PR_FIELDS = ["linked issue", "summary", "files changed", "tests run", "docs updated", "unresolved blockers", "handoff recommendations", "remaining risks"]


def parse_linked_issue_result(pr_body: str, pr_title: str = "") -> LinkedIssueParseResult:
    """Parse GitHub-authoritative body linkage while retaining title evidence."""
    explicit: list[LinkedIssueCandidate] = []
    bare: list[LinkedIssueCandidate] = []
    for source, text in (("title", pr_title or ""), ("body", pr_body or "")):
        source_explicit, source_bare = _extract_candidates(text, source)
        explicit.extend(source_explicit)
        bare.extend(source_bare)
    explicit = _deduplicate_candidates(explicit)
    bare = _deduplicate_candidates(bare)
    unique_explicit = {(candidate.repository.lower() if candidate.repository else None, candidate.issue_number) for candidate in explicit}
    if len(unique_explicit) == 1:
        repository, issue_number = next(iter(unique_explicit))
        if repository is not None:
            return LinkedIssueParseResult(status=LinkedIssueParseStatus.MANUAL_REVIEW, repository=repository, explicit_candidates=explicit, bare_references=bare, reasons=["Repository-qualified linked issues are not supported end-to-end; manual review is required."])
        return LinkedIssueParseResult(status=LinkedIssueParseStatus.RESOLVED, issue_number=issue_number, explicit_candidates=explicit, bare_references=bare, reasons=[f"Exactly one authoritative closing target was detected: #{issue_number}."])
    if len(unique_explicit) > 1:
        targets = ", ".join(_format_target(repository, number) for repository, number in sorted(unique_explicit, key=_target_sort_key))
        return LinkedIssueParseResult(status=LinkedIssueParseStatus.MANUAL_REVIEW, explicit_candidates=explicit, bare_references=bare, reasons=[f"Multiple unique explicit closing targets were detected: {targets}."])
    if bare:
        authoritative_looking = [candidate for candidate in bare if candidate.keyword]
        if authoritative_looking:
            details = ", ".join(f"{candidate.keyword} {candidate.normalized_target}" for candidate in authoritative_looking)
            reason = f"Unsupported or non-authoritative closing-looking issue references were detected: {details}."
        else:
            targets = ", ".join(candidate.normalized_target for candidate in bare)
            reason = f"Only non-authoritative issue references were detected: {targets}."
        return LinkedIssueParseResult(status=LinkedIssueParseStatus.MANUAL_REVIEW, bare_references=bare, reasons=[reason])
    return LinkedIssueParseResult(status=LinkedIssueParseStatus.NONE)


def parse_linked_issue(pr_body: str, pr_title: str = "") -> int | None:
    result = parse_linked_issue_result(pr_body, pr_title)
    return result.issue_number if result.status == LinkedIssueParseStatus.RESOLVED else None


def _extract_candidates(text: str, source: str) -> tuple[list[LinkedIssueCandidate], list[LinkedIssueCandidate]]:
    masked = _mask_non_authoritative_markdown(text)
    explicit: list[LinkedIssueCandidate] = []
    bare: list[LinkedIssueCandidate] = []
    occupied_target_spans: list[tuple[int, int]] = []
    for match in EXPLICIT_LINK_RE.finditer(masked):
        candidate = _candidate_from_match(match, source, explicit=source == "body")
        (explicit if source == "body" else bare).append(candidate)
        occupied_target_spans.append(match.span("target"))
    for match in UNSUPPORTED_LINK_RE.finditer(masked):
        bare.append(_candidate_from_match(match, source, explicit=False))
        occupied_target_spans.append(match.span("target"))
    for match in ISSUE_REFERENCE_RE.finditer(masked):
        if _overlaps(match.span("target"), occupied_target_spans):
            continue
        line_start = masked.rfind("\n", 0, match.start("target")) + 1
        prefix = masked[max(line_start, match.start("target") - 90):match.start("target")]
        prefix_match = _AUTHORITATIVE_PREFIX_RE.search(prefix)
        keyword = prefix_match.group("keyword").lower() if prefix_match else None
        repository, issue_number = _target_identity(match)
        bare.append(LinkedIssueCandidate(issue_number=issue_number, repository=repository, keyword=keyword, source=source, position=match.start("target"), raw_target=match.group("target"), explicit=False))
    return explicit, bare


def _candidate_from_match(match: re.Match[str], source: str, explicit: bool) -> LinkedIssueCandidate:
    repository, issue_number = _target_identity(match)
    return LinkedIssueCandidate(issue_number=issue_number, repository=repository, keyword=match.group("keyword").lower(), source=source, position=match.start("target"), raw_target=match.group("target"), explicit=explicit)


def _target_identity(match: re.Match[str]) -> tuple[str | None, int]:
    url_repository = match.group("url_repository")
    repository = url_repository or match.group("repository")
    if url_repository and url_repository.lower() == _CANONICAL_REPOSITORY:
        repository = None
    number = match.group("url_number") or match.group("number")
    return repository, int(number)


def _mask_non_authoritative_markdown(text: str) -> str:
    masked = _HTML_COMMENT_RE.sub(lambda match: _mask_text(match.group(0)), text or "")
    output: list[str] = []
    fence_marker: str | None = None
    for line in masked.splitlines(keepends=True):
        if line.startswith(("    ", "\t")):
            output.append(_mask_text(line)); continue
        stripped = line.lstrip()
        marker = stripped[:3] if stripped.startswith(("```", "~~~")) else None
        if marker:
            if fence_marker is None: fence_marker = marker
            elif marker == fence_marker: fence_marker = None
            output.append(_mask_text(line)); continue
        if fence_marker is not None or stripped.startswith(">"):
            output.append(_mask_text(line)); continue
        output.append(_INLINE_CODE_RE.sub(lambda match: _mask_text(match.group(0)), line))
    return "".join(output)


def _mask_text(text: str) -> str:
    return "".join("\n" if character == "\n" else "\r" if character == "\r" else " " for character in text)


def _overlaps(span: tuple[int, int], occupied: list[tuple[int, int]]) -> bool:
    return any(span[0] < other[1] and other[0] < span[1] for other in occupied)


def _deduplicate_candidates(candidates: list[LinkedIssueCandidate]) -> list[LinkedIssueCandidate]:
    seen: set[tuple[str | None, int, str | None, str, bool]] = set()
    result: list[LinkedIssueCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (0 if item.source == "title" else 1, item.position)):
        key = (candidate.repository.lower() if candidate.repository else None, candidate.issue_number, candidate.keyword, candidate.source, candidate.explicit)
        if key not in seen:
            seen.add(key); result.append(candidate)
    return result


def _format_target(repository: str | None, issue_number: int) -> str:
    return f"{repository}#{issue_number}" if repository else f"#{issue_number}"


def _target_sort_key(target: tuple[str | None, int]) -> tuple[str, int]:
    repository, issue_number = target
    return repository or "", issue_number


def has_markdown_heading(text: str, heading: str) -> bool:
    return bool(re.compile(rf"^#+\s+{re.escape(heading)}\s*$", re.IGNORECASE | re.MULTILINE).search(text or ""))


def missing_final_report_fields(pr_body: str) -> list[str]:
    return [field for field in REQUIRED_PR_FIELDS if not has_markdown_heading(pr_body, field)]


def has_validation_command(pr_body: str) -> bool:
    lowered = (pr_body or "").lower()
    return any(command in lowered for command in ["validate-all.sh", "pytest", "validate-repo-structure.sh", "cloud build", "cloudbuild"])
