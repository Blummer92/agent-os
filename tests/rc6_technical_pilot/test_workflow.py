from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/rc6-technical-pilot.yml"
FROZEN_SHA = "ca980c38d74b8d3ab30ca67461a9f576281edc75"


def _text():
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_manual_read_only_and_sha_pinned():
    text = _text()
    assert text.startswith("name: RC6 Technical Pilot\n")
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "push:" not in text
    assert "schedule:" not in text
    assert "permissions:\n  contents: read\n" in text
    assert f'default: "{FROZEN_SHA}"' in text
    assert "path: baseline" in text
    assert "ref: ${{ inputs.frozen_sha }}" in text
    assert "git -C baseline rev-parse HEAD" in text


def test_workflow_runs_only_focused_tests_and_runner_then_uploads_evidence():
    text = _text()
    assert "pytest -q runner-source/tests/rc6_technical_pilot" in text
    assert "runner-source/scripts/agent_os_rc6_technical_pilot.py" in text
    assert "actions/upload-artifact@v4" in text
    assert "rc6-technical-pilot.json" in text
    assert "rc6-technical-pilot.md" in text
    assert "$GITHUB_STEP_SUMMARY" in text
    assert "./scripts/validate-all.sh" not in text
    assert "gh issue" not in text
    assert "curl " not in text


def test_workflow_uses_separate_runner_and_frozen_baseline_checkouts():
    text = _text()
    assert text.count("uses: actions/checkout@v4") == 2
    assert "path: runner-source" in text
    assert "path: baseline" in text
    assert "RC6_BASELINE_ROOT: ${{ github.workspace }}/baseline" in text
