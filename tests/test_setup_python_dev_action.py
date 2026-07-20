from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/setup-python-dev/action.yml"
WORKFLOWS = ROOT / ".github/workflows"
ACTION_REFERENCE = "uses: ./.github/actions/setup-python-dev"
EXPECTED_CALLERS = {
    "agent-os-issue-acceptance-report.yml",
    "agent-os-issue-label-apply-dry-run.yml",
    "agent-os-issue-label-report.yml",
}


def _assert_action_contract(content: str) -> None:
    required = [
        "runs:",
        "using: composite",
        "uses: actions/setup-python@v5",
        'python-version: "3.11"',
        'cache: "pip"',
        "cache-dependency-path: requirements-dev.txt",
        "shell: bash",
        "run: python -m pip install -r requirements-dev.txt",
    ]
    missing = [pattern for pattern in required if pattern not in content]
    assert not missing, f"shared setup action is missing required contract: {missing}"

    forbidden = [
        "actions/checkout",
        "pip install --upgrade pip",
        "inputs:",
        "profile",
    ]
    present = [pattern for pattern in forbidden if pattern in content]
    assert not present, f"shared setup action contains forbidden behavior: {present}"


def test_shared_python_dev_action_has_narrow_contract():
    content = ACTION.read_text(encoding="utf-8")
    _assert_action_contract(content)
    assert content.count("python -m pip install -r requirements-dev.txt") == 1


def test_exactly_three_approved_workflows_use_shared_action():
    callers = {
        path.name
        for path in WORKFLOWS.glob("*.yml")
        if ACTION_REFERENCE in path.read_text(encoding="utf-8")
    }
    assert callers == EXPECTED_CALLERS


@pytest.mark.parametrize(
    "broken",
    [
        'cache: "none"',
        "run: echo dependency installation removed",
    ],
)
def test_action_contract_rejects_missing_cache_or_installation(broken: str):
    content = ACTION.read_text(encoding="utf-8")
    if broken.startswith("cache:"):
        content = content.replace('cache: "pip"', broken)
    else:
        content = content.replace(
            "run: python -m pip install -r requirements-dev.txt",
            broken,
        )

    with pytest.raises(AssertionError):
        _assert_action_contract(content)
