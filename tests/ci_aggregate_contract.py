"""Test-only assertion for the single hosted aggregate execution path."""
from pathlib import Path
import re

import yaml


def assert_single_hosted_aggregate(root: Path) -> None:
    workflow = root / ".github/workflows/agent-os-validation.yml"
    jobs = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]
    steps = [
        (job_id, step) for job_id, job in jobs.items()
        for step in job.get("steps", []) if "run" in step
    ]
    execution_steps = [
        (job_id, step) for job_id, step in steps
        if re.search(r"(?:^|[\s/])(?:ci-local|validate-all)\.sh\b", step["run"])
    ]
    assert len(execution_steps) == 1
    job_id, step = execution_steps[0]
    assert job_id == "validate"
    assert step["id"] == "aggregate"
    assert step["run"] == "bash ./scripts/ci-local.sh --hosted"
    wrapper = (root / "scripts/ci-local.sh").read_text(encoding="utf-8")
    assert wrapper.count("./scripts/validate-all.sh") == 1
    assert re.search(r"^\s*bash \./scripts/validate-all\.sh [|][|]", wrapper, re.MULTILINE)
