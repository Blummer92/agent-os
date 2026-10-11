import json
import os
from pathlib import Path
import subprocess
import tempfile

import yaml

ROOT = Path.home() / "agent-os-ready-recovery-3486"
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"

TARGET = "868bd7e46a682adb9c31a215b829c25c0dc130f8"
MAIN = "b7e42a6507fd3ea1eb8611ae791b1dd83b617d35"
REPAIR = "1a506b4c07eab77f3234401d3b2f4fe1811bafed"

data = yaml.safe_load(WORKFLOW.read_text())
steps = data["jobs"]["validate"]["steps"]
candidate = next(step["run"] for step in steps if step.get("id") == "candidate")

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys

a = sys.argv[1:]
e = os.environ

if a[:2] == ["pr", "view"]:
    print(json.dumps({
        "state": "OPEN",
        "isDraft": e.get("MOCK_DRAFT") == "true",
        "headRefOid": e.get("MOCK_HEAD", e["EXPECTED_HEAD_SHA"]),
        "baseRefOid": e["EXPECTED_MAIN_SHA"],
        "baseRefName": "main",
        "headRefName": "agent/3372-chatgpt-mcp-publication-allowlist",
    }))
    sys.exit(0)

if not a or a[0] != "api":
    sys.exit("Unexpected gh operation: " + repr(a))

endpoint = next((v for v in a if v.startswith("repos/")), "")

if endpoint.endswith("/commits/main"):
    print(e.get("MOCK_MAIN", e["EXPECTED_MAIN_SHA"]))
elif "/git/ref/heads/" in endpoint:
    print(e["EXPECTED_WORKFLOW_SHA"])
elif endpoint.endswith(
    "/actions/workflows/agent-os-validation.yml"
):
    print("314047915")
elif "/actions/workflows/agent-os-validation.yml/runs?" in endpoint:
    attempts = int(e.get("MOCK_ATTEMPTS", "1"))
    title = "agent-os-ready-recovery:3486:" + e["EXPECTED_HEAD_SHA"]
    for index in range(attempts):
        run_id = 9001 + index
        if e.get("MOCK_MISSING_CURRENT") == "true":
            run_id += 100
        print(f"{run_id}\t{title}")
elif "/actions/runs/" in endpoint and "/jobs?" in endpoint:
    print(e.get("MOCK_JOB_COUNT", "0"))
elif "/actions/runs/" in endpoint:
    print(json.dumps({
        "status": "completed",
        "conclusion": e.get("MOCK_CONCLUSION", "action_required"),
        "event": "pull_request",
        "head_sha": e["EXPECTED_HEAD_SHA"],
        "head_branch": "agent/3372-chatgpt-mcp-publication-allowlist",
        "workflow_id": int(e.get("MOCK_WORKFLOW_ID", "314047915")),
        "name": "Changed workflow display title",
        "path": ".github/workflows/agent-os-validation.yml",
        "pull_requests": [{
            "number": int(e.get("MOCK_SOURCE_PR", "3486"))
        }],
    }))
else:
    sys.exit("Unexpected API endpoint: " + endpoint)
'''

def execute(**overrides):
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        fake = tmp / "gh"
        fake.write_text(FAKE_GH)
        fake.chmod(0o755)

        output = tmp / "github-output"
        output.touch()

        env = os.environ.copy()
        env.update({
            "PATH": str(tmp) + ":" + env["PATH"],
            "PR_NUMBER": "3486",
            "EXPECTED_HEAD_SHA": TARGET,
            "EXPECTED_MAIN_SHA": MAIN,
            "EXPECTED_WORKFLOW_SHA": REPAIR,
            "SOURCE_VALIDATION_RUN_ID": "38164744779",
            "READY_RECOVERY": "true",
            "GITHUB_SHA": REPAIR,
            "GITHUB_ACTOR": "Blummer92",
            "GITHUB_REPOSITORY": "Blummer92/agent-os",
            "GITHUB_REF_TYPE": "branch",
            "GITHUB_REF_NAME": "agent/3486-ready-validation-recovery",
            "GITHUB_RUN_ID": "9001",
            "GITHUB_OUTPUT": str(output),
            "GH_TOKEN": "offline-test-only",
            "MAX_READY_RECOVERY_ATTEMPTS": "2",
        })
        env.update(overrides)

        result = subprocess.run(
            ["bash", "-c", candidate],
            env=env,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout + result.stderr, output.read_text()

cases = [
    ("valid Ready recovery", {}, True),
    ("Draft PR rejected", {"MOCK_DRAFT": "true"}, False),
    ("stale candidate rejected", {"MOCK_HEAD": "a" * 40}, False),
    ("main changed rejected", {"MOCK_MAIN": "b" * 40}, False),
    ("wrong actor rejected", {"GITHUB_ACTOR": "other-user"}, False),
    ("wrong workflow ref rejected", {"GITHUB_SHA": "c" * 40}, False),
    ("wrong workflow ID rejected", {"MOCK_WORKFLOW_ID": "123"}, False),
    ("wrong source PR rejected", {"MOCK_SOURCE_PR": "9999"}, False),
    ("executed source jobs rejected", {"MOCK_JOB_COUNT": "2"}, False),
    ("non-zero-job conclusion rejected", {"MOCK_CONCLUSION": "success"}, False),
    ("third attempt rejected", {"MOCK_ATTEMPTS": "3"}, False),
    ("missing current run rejected", {"MOCK_MISSING_CURRENT": "true"}, False),
]

failed = 0
for name, overrides, expected_success in cases:
    code, logs, output = execute(**overrides)
    actual_success = code == 0 and "mode=ready-recovery" in output
    passed = actual_success == expected_success
    print(("PASS" if passed else "FAIL") + ": " + name)
    if not passed:
        failed += 1
        print(logs[-1000:])

print(f"\nDynamic admission QA: {len(cases) - failed}/{len(cases)} passed")
raise SystemExit(1 if failed else 0)
