"""Parse CLI flags into a Population; no network, environment, or report logic."""

import argparse

from .errors import ValidationError
from .inputs import MAX_ISSUES, MAX_PR_PAGES, freeze_population, issue_number, valid_timestamp


class _Parser(argparse.ArgumentParser):
    """Map usage errors to a fixed message without echoing user-supplied values."""

    def error(self, message):
        raise ValidationError("invalid_arguments", "Invalid arguments; use --help for usage.", "arguments")


def _tokens(value, field):
    """Reject empty comma-separated positions, including a trailing comma."""
    if len(value) > 8000:
        raise ValidationError("invalid_list", "Issue list is too long.", field)
    parts = value.split(",")
    if len(parts) > MAX_ISSUES or any(not part.strip() for part in parts):
        raise ValidationError("invalid_list", "Expected nonempty comma-separated entries.", field)
    return parts


def _parse_admitted(text):
    """Parse distinct positive admissions with a real offset-aware timestamp."""
    admitted = {}
    for part in _tokens(text, "admitted") if text is not None else ():
        number, sep, stamp = part.partition(":")
        issue = issue_number(number, "admitted")
        if issue in admitted:
            raise ValidationError("duplicate_admission", "Admission issue appears more than once.", "admitted")
        if not sep or not valid_timestamp(stamp.strip()):
            raise ValidationError("invalid_timestamp", "Admission requires an offset-aware ISO timestamp.", "admitted")
        admitted[issue] = {"admitted": True, "admitted_at": stamp.strip()}
    return admitted


def parse_args(argv):
    """Parse and freeze the CLI arguments; argparse still handles --help."""
    parser = _Parser(description="Measure frozen Agent OS issue reliability (GitHub GET only).",
                     allow_abbrev=False)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issues", required=True, help="comma-separated frozen issue numbers")
    parser.add_argument("--admitted", help="optional <issue>:<timestamp> entries")
    parsed = parser.parse_args(argv)
    numbers = [issue_number(x, "issues") for x in _tokens(parsed.issues, "issues")]
    return freeze_population(parsed.owner, parsed.repo, numbers, _parse_admitted(parsed.admitted),
                             max_pr_pages=MAX_PR_PAGES)
