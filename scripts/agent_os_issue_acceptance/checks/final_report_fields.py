from __future__ import annotations

from ..models import CheckResult, Status
from ..parse_pr import missing_final_report_fields


def check(pr_body: str) -> CheckResult:
    missing = missing_final_report_fields(pr_body)
    if missing:
        return CheckResult(
            "required PR report fields",
            Status.FAIL,
            "Missing required Agent OS PR report fields.",
            missing,
        )
    return CheckResult("required PR report fields", Status.PASS, "All required PR report fields are present.")
