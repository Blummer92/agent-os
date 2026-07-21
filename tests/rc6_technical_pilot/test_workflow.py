from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/rc6-technical-pilot.yml"
FROZEN_SHA = "ca980c38d74b8d3ab30ca67461a9f576281edc75"


def _text():
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_manual_read_only_sha_pinned_and_serialized():
    text = _text()
    assert text.startswith("name: RC6 Technical Pilot\n")
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "push:" not in text
    assert "schedule:" not in text
    assert "permissions:\n  contents: read\n" in text
    assert f'default: "{FROZEN_SHA}"' in text
    assert "concurrency:\n  group: rc6-technical-pilot\n  cancel-in-progress: false\n" in text
    assert 'test "$GITHUB_REF" = "refs/heads/main"' in text
    assert 'test "$runner_sha" = "$GITHUB_SHA"' in text
    assert 'test "$baseline_sha" = "$FROZEN_SHA"' in text


def test_workflow_preflights_then_runs_focused_tests_and_pilot():
    text = _text()
    assert "Run non-executing frozen-baseline preflight" in text
    assert "--preflight-only" in text
    assert "pytest -q runner-source/tests/rc6_technical_pilot" in text
    assert "runner-source/scripts/agent_os_rc6_technical_pilot.py" in text
    assert "actions/upload-artifact@v4" in text
    assert "rc6-technical-pilot.json" in text
    assert "rc6-technical-pilot.md" in text
    assert "SHA256SUMS" in text
    assert "workflow-failure" in text
    assert "$GITHUB_STEP_SUMMARY" in text
    assert "./scripts/validate-all.sh" not in text
    assert "gh issue" not in text
    assert "curl " not in text


def test_workflow_uses_separate_verified_runner_and_frozen_checkouts():
    text = _text()
    assert text.count("uses: actions/checkout@v4") == 2
    assert "ref: ${{ github.sha }}" in text
    assert "path: runner-source" in text
    assert "ref: ${{ inputs.frozen_sha }}" in text
    assert "path: baseline" in text
    assert "git -C runner-source rev-parse HEAD" in text
    assert "git -C baseline rev-parse HEAD" in text
    assert "RC6_BASELINE_ROOT: ${{ github.workspace }}/baseline" in text


def test_workflow_evidence_is_traceable_and_retained_for_review():
    text = _text()
    assert "${{ github.run_id }}" in text
    assert "${{ github.run_attempt }}" in text
    assert "name: ${{ env.ARTIFACT_NAME }}" in text
    assert "retention-days: 90" in text
    assert "Artifact: `%s`" in text
    assert "Runner SHA: `%s`" in text
    assert "Frozen SHA: `%s`" in text
