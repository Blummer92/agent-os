import io
import json
from pathlib import Path

from scripts.agent_os_issue_labels.draft_cli import main

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
FIXTURE = ROOT / "tests/agent_os_issue_labels/fixtures/issue_draft/valid_tier0.yml"


def valid_input() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_file_and_stdin_json_paths_are_equivalent(tmp_path, monkeypatch, capsys):
    path = tmp_path / "draft.yml"
    path.write_text(valid_input(), encoding="utf-8")
    args = [
        "--issue-form",
        str(FORM),
        "--label-map",
        str(MAP),
        "--format",
        "json",
    ]

    assert main(["--input", str(path), *args]) == 0
    file_output = capsys.readouterr().out

    monkeypatch.setattr("sys.stdin", io.StringIO(valid_input()))
    assert main(["--input", "-", *args]) == 0
    stdin_output = capsys.readouterr().out

    assert json.loads(file_output) == json.loads(stdin_output)
    assert json.loads(file_output)["write_authorized"] is False


def test_malformed_input_returns_fail_without_traceback(tmp_path, capsys):
    path = tmp_path / "bad.yml"
    path.write_text("title: one\ntitle: two\nfields: {}\n", encoding="utf-8")

    code = main(
        [
            "--input",
            str(path),
            "--issue-form",
            str(FORM),
            "--label-map",
            str(MAP),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["overall_status"] == "fail"
    assert payload["write_authorized"] is False
