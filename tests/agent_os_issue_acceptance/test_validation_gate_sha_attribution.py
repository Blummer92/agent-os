"""Workflow-contract regression coverage for #1270.

The Agent OS Validation Gate is the authoritative aggregate run. On a
``pull_request`` event ``GITHUB_SHA`` is the ephemeral merge commit, not the
pull-request head, so a summary that reports only ``GITHUB_SHA`` cannot satisfy
the exact-head evidence contract. The summary must therefore report both SHAs
on separate, non-confusable labelled lines.

Reporting only: these assertions also pin the excluded surfaces (checkout,
permissions, concurrency) that #1270 forbids changing.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"

HEAD_SHA_LABEL = "- Head SHA (pull request head): "
MERGE_SHA_LABEL = "- Checked-out (merge) SHA: "


def _content() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _summary_step() -> str:
    content = _content()
    start = content.index("- name: Publish validation summary")
    return content[start:]


def _summary_line(prefix: str) -> str:
    for line in _summary_step().splitlines():
        stripped = line.strip()
        if stripped.startswith(f'echo "{prefix}'):
            return stripped
    raise AssertionError(
        f"validation summary must emit a line labelled {prefix!r}"
    )


def test_summary_reports_the_exact_pull_request_head_sha():
    content = _content()

    assert "github.event.pull_request.head.sha" in content
    assert "PR_HEAD_SHA: ${{ github.event.pull_request.head.sha }}" in content
    assert "PR_HEAD_SHA" in _summary_line(HEAD_SHA_LABEL)


def test_summary_retains_the_checked_out_merge_sha_under_a_distinct_label():
    assert "$GITHUB_SHA" in _summary_line(MERGE_SHA_LABEL)


def test_head_and_merge_shas_are_separate_non_confusable_labelled_lines():
    step = _summary_step()
    head_line = _summary_line(HEAD_SHA_LABEL)
    merge_line = _summary_line(MERGE_SHA_LABEL)

    assert head_line != merge_line
    assert step.index(head_line) < step.index(merge_line)

    # Neither line may carry the other's SHA source, so a reader cannot mistake
    # one commit identity for the other.
    assert "$GITHUB_SHA" not in head_line
    assert "PR_HEAD_SHA" not in merge_line

    # The former bare, ambiguous attribution must not return.
    assert 'echo "- Commit: \\`$GITHUB_SHA\\`"' not in step


def test_sha_attribution_fix_does_not_change_excluded_surfaces():
    content = _content()

    # Checkout semantics: no ref: override may be introduced (#1270 forbids
    # changing which commit is validated).
    assert "uses: actions/checkout@v7" in content
    checkout = content.index("- name: Check out repository")
    setup_python = content.index("- name: Set up Python")
    assert "ref:" not in content[checkout:setup_python]

    assert "permissions:\n  contents: read\n" in content
    assert (
        "concurrency:\n"
        "  group: agent-os-validation-"
        "${{ github.event.pull_request.number || github.ref }}\n"
        "  cancel-in-progress: true\n"
    ) in content
    assert "name: Agent OS Validation Gate" in content
    assert "name: Run aggregate validation" in content
