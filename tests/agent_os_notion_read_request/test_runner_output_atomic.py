"""Local receipt-publication integrity, with a real bounded write failure."""
import json
import subprocess
import sys

import pytest

from scripts.agent_os_notion_read_request.runner import main


@pytest.mark.parametrize("has_previous_receipt", (False, True), ids=("fresh", "previous"))
def test_short_local_file_write_does_not_corrupt_receipt(
    tmp_path, capsys, has_previous_receipt,
):
    resource = pytest.importorskip("resource")
    if not hasattr(resource, "RLIMIT_FSIZE"):
        pytest.skip("requires POSIX local file-size limit")

    transport = tmp_path / "transport.json"
    transport.write_text("{}", encoding="utf-8")
    output = tmp_path / "result.json"
    argv = [
        "--transport", str(transport),
        "--repository", "Blummer92/agent-os",
        "--allowed-actor", "Blummer92",
        "--output", str(output),
    ]
    expected_prior = None
    if has_previous_receipt:
        assert main([*argv, "--generated-at", "previous-local-run"]) == 0
        expected_prior = output.read_bytes()
        assert json.loads(expected_prior)["generated_at"] == "previous-local-run"
        capsys.readouterr()

    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "import resource, signal, sys; "
            "from scripts.agent_os_notion_read_request.runner import main; "
            "signal.signal(signal.SIGXFSZ, signal.SIG_IGN); "
            "_, hard = resource.getrlimit(resource.RLIMIT_FSIZE); "
            "resource.setrlimit(resource.RLIMIT_FSIZE, (256, hard)); "
            "raise SystemExit(main(sys.argv[1:]))",
            *argv, "--generated-at", "current-local-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert child.returncode == 1
    assert child.stderr == ""
    result = json.loads(child.stdout)
    assert result["dispatch_status"] == "failed"
    assert result["dispatch_reason"] == "receipt-write-failed"
    assert result["failure"]["detail"] is None
    assert result["failure"]["phase"] == "write"
    assert not result["notion_writes_performed"]
    assert not result["drive_writes_performed"]
    if expected_prior is None:
        assert not output.exists()
    else:
        assert output.read_bytes() == expected_prior
    assert {path.name for path in tmp_path.iterdir()} == (
        {"transport.json", "result.json"} if has_previous_receipt else {"transport.json"}
    )
