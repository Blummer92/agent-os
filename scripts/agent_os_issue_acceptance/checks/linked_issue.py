from __future__ import annotations

from ..models import CheckResult, Status
from ..parse_pr import parse_linked_issue


def check(pr_body: str, pr_title: str = "") -> CheckResult:
    issue_number = parse_linked_issue(pr_body, pr_title)
    if issue_number is None:
        return CheckResult("linked issue", Status.FAIL, "No linked issue reference was detected.")
    return CheckResult("linked issue", Status.PASS, f"Detected linked issue #{issue_number}.")
