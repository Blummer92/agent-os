from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/picture-perfect-typescript-validation.yml"


def _content() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_path_triggered_for_picture_perfect_only() -> None:
    content = _content()
    assert "name: Picture Perfect TypeScript Validation" in content
    assert '"08_Tooling/instructional-materials-coach/picture-perfect-coach/**"' in content
    assert "push:" not in content
    assert "types: [opened, synchronize, reopened]" in content
    assert "edited" not in content


def test_workflow_is_read_only_and_bounded() -> None:
    content = _content()
    assert "contents: read" in content
    assert "contents: write" not in content
    assert "timeout-minutes: 15" in content
    assert "cancel-in-progress: true" in content


def test_workflow_checks_out_exact_pr_source_head() -> None:
    content = _content()
    assert "ref: ${{ github.event.pull_request.head.sha }}" in content
    assert 'test "$(git rev-parse HEAD)" = "${{ github.event.pull_request.head.sha }}"' in content
    assert "tested_sha=%s" in content


def test_workflow_runs_package_owned_canonical_check() -> None:
    content = _content()
    assert "node-version: \"22.12.0\"" in content
    assert "npm ci" in content
    assert content.count("npm run check") >= 1
    assert "npm run test:e2e" not in content
    assert "package-lock.json" in content
