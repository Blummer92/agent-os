"""Pin the #3732 Ready receipt-retrieval route (#3446).

Regression: on 2026-10-25 the native host tried generic ``fetch`` against
the binary Actions artifact ZIP endpoint, which rejected it as an
unsupported URL, and stopped instead of switching to the dedicated
artifact-download action that was available in the same session. The
host-consumption contract must therefore name the retrieval action
explicitly; "read the receipt" alone does not tell a tool-selecting host
which action to use, and this test locks that sentence against silent
regression. It pins documentation text only and adds no production
code path, evaluator, receipt format, or storage system.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/3446-ready-admission-ingress.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_ready_receipt_retrieval_names_dedicated_download_action() -> None:
    contract = normalized(CONTRACT)
    assert "fetch_workflow_run_artifacts" in contract
    assert "download_workflow_artifact" in contract
    assert "agent-os-ready-admission-<run>-<attempt>" in contract


def test_ready_receipt_retrieval_forbids_generic_fetch_for_artifact_zip() -> None:
    contract = normalized(CONTRACT)
    assert "never with generic `fetch`" in contract
    assert "rejects the binary artifact ZIP endpoint as an unsupported URL" in contract
    assert "unsupported URL` rejection for the artifact endpoint is a tool-selection signal" in contract
    assert "not a missing receipt connection" in contract


def test_ready_receipt_retrieval_requires_continuation_not_restart() -> None:
    contract = normalized(CONTRACT)
    assert "switch to `download_workflow_artifact`" in contract
    assert "fetch_workflow_job_logs" in contract
    assert "do not stop, do not re-post the admission request" in contract
    assert "read `receipt.json` from the ZIP and proceed to step 3" in contract
