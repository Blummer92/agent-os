"""Freeze identifiers and validate admission evidence without I/O or CLI dependencies."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from .errors import ValidationError

MAX_ISSUE_NUMBER = 2_147_483_647
MAX_ISSUES = 100
DEFAULT_PR_PAGES = 10
MAX_PR_PAGES = 30


def positive_issue(number):
    """Return whether a number is an exact, supported positive issue identifier."""
    return type(number) is int and 1 <= number <= MAX_ISSUE_NUMBER


def issue_number(text, field):
    """Decode a bounded decimal issue id, or raise a structured input error."""
    value = text.strip()
    if not re.fullmatch(r"[0-9]{1,10}", value) or not positive_issue(int(value)):
        raise ValidationError("invalid_issue", "Expected a positive, bounded issue number.", field)
    return int(value)


def valid_timestamp(value):
    """Require a real offset-aware ISO timestamp, not a date or naive local time."""
    if type(value) is not str or not 1 <= len(value) <= 64 or "T" not in value:
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except (ValueError, OverflowError):
        return False


def frozen_numbers(numbers):
    """Copy validated input identifiers while deduplicating in first-seen order."""
    if not isinstance(numbers, Sequence) or isinstance(numbers, (str, bytes)):
        raise ValidationError("invalid_population", "Expected a nonempty issue sequence.", "issues")
    if not 1 <= len(numbers) <= MAX_ISSUES:
        raise ValidationError("invalid_population", "Expected between 1 and 100 issue entries.", "issues")
    if not all(positive_issue(number) for number in numbers):
        raise ValidationError("invalid_issue", "Expected positive, bounded issue numbers.", "issues")
    return tuple(dict.fromkeys(numbers))


def validate_slug(value, field):
    """Validate a single GitHub path segment; reject URLs and dot segments."""
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value) or value in (".", ".."):
        raise ValidationError("invalid_repository", "Expected a GitHub name, not a URL or path.", field)


def _admission_pairs(admitted, frozen):
    """Detach and validate programmatic admission evidence for the frozen population."""
    if admitted is None:
        return ()
    if not isinstance(admitted, Mapping):
        raise ValidationError("invalid_admission", "Expected admission records by issue number.", "admitted")
    pairs = []
    for issue, record in admitted.items():
        if not positive_issue(issue) or issue not in frozen:
            raise ValidationError("outside_population", "Admitted issue is not in the frozen population.", "admitted")
        if not isinstance(record, Mapping) or type(record.get("admitted")) is not bool:
            raise ValidationError("invalid_admission", "Expected a boolean admission status.", "admitted")
        flag, stamp = record["admitted"], record.get("admitted_at")
        if (flag and not valid_timestamp(stamp)) or (not flag and stamp is not None):
            raise ValidationError("invalid_timestamp", "Admission requires an offset-aware ISO timestamp.", "admitted")
        if flag:
            pairs.append((issue, stamp))
    return tuple(pairs)


@dataclass(frozen=True)
class Population:
    """Validated immutable acquisition inputs; admission stores only explicit positive evidence."""

    repository: str
    issues: tuple[int, ...]
    admitted: tuple[tuple[int, str], ...]
    max_pr_pages: int


def freeze_population(owner, repository, issue_numbers, admitted_map=None, max_pr_pages=DEFAULT_PR_PAGES):
    """Bind repository, issues, admission and page limit before the first read."""
    validate_slug(owner, "owner")
    validate_slug(repository, "repo")
    issues = frozen_numbers(issue_numbers)
    if type(max_pr_pages) is not int or not 1 <= max_pr_pages <= MAX_PR_PAGES:
        raise ValidationError("invalid_page_limit", "Expected 1–30 PR pages.", "max_pr_pages")
    return Population(f"{owner}/{repository}", issues, _admission_pairs(admitted_map, issues), max_pr_pages)
