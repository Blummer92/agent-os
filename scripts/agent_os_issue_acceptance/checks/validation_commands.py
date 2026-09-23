from __future__ import annotations

from ..models import CheckResult, Status
from ..parse_pr import has_validation_command


def check(pr_body: str) -> CheckResult:
    if not has_validation_command(pr_body):
        return CheckResult("validation commands", Status.WARN, "No validation command was reported in the PR body.")
    return CheckResult("validation commands", Status.PASS, "Validation command evidence is present.")
