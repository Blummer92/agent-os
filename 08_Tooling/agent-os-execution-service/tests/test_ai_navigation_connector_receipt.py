"""Pure connector retrieval seam tests; fixtures are NOT live GitHub provenance."""
import pytest
import agent_os_execution_service.ai_navigation_connector_receipt as seam

SHA = "a" * 40
BIND = dict(repository=seam.REPOSITORY, run_id=123, run_attempt=2,
            source_sha=SHA, issue_number=3970, comment_id=99, actor="Blummer92")


def _run():
    return dict(id=123, run_attempt=2, head_sha=SHA,
                path=".github/workflows/agent-os-ai-navigation-discover.yml",
                event="issue_comment", status="completed", conclusion="success",
                repository={"full_name": seam.REPOSITORY},
                head_repository={"full_name": seam.REPOSITORY})


def _art(i, target=False):
    return dict(id=i, name="agent-os-ai-navigation-123-2" if target else f"other-{i}",
                expired=False, digest="sha256:" + "b" * 64, size_in_bytes=3,
                workflow_run=dict(id=123, head_sha=SHA))


def _fetch(pages, meta=None):
    calls = []
    def fetch(url):
        calls.append(url)
        if url.endswith("/actions/runs/123"):
            return _run() if meta is None else meta
        return pages[int(url.split("page=")[-1]) - 1]
    return fetch, calls


def test_two_pages_exact_metadata_then_canonical_validator(monkeypatch):
    pages = [{"total_count": 101, "artifacts": [_art(i) for i in range(1, 101)]},
             {"total_count": 101, "artifacts": [_art(999, target=True)]}]
    fetch, calls = _fetch(pages)
    seen = []
    def validate(**kwargs):
        seen.append(kwargs)
        return dict(status="verified-consistent", reason="run-bound-and-well-formed", authentic=False)
    monkeypatch.setattr(seam, "validate_retrieved_receipt", validate)
    result = seam.retrieve_and_validate_connector_receipt(
        expected_binding=BIND, fetch_json=fetch, download_zip=lambda ident: b"zip" if ident == 999 else None)
    assert result["status"] == "verified-consistent" and result["authentic"] is False
    assert len(calls) == 3 and len(seen[0]["listing"]["artifacts"]) == 101
    assert all(url.startswith("https://api.github.com/repos/Blummer92/agent-os/") for url in calls)


@pytest.mark.parametrize("pages,reason", [
    ([{"total_count": 101, "artifacts": [_art(i) for i in range(99)]}], "artifact-listing-incomplete"),
    ([{"total_count": 2, "artifacts": [_art(55, True), _art(55)]}], "artifact-ids-invalid"),
    ([{"total_count": 101, "artifacts": [_art(i) for i in range(100)]},
      {"total_count": 102, "artifacts": [_art(999, True)]}], "artifact-total-changed"),
    ([{"total_count": "one", "artifacts": [_art(999, True)]}], "artifact-listing-malformed"),
])
def test_invalid_listings_fail_closed(pages, reason):
    fetch, _ = _fetch(pages)
    result = seam.retrieve_and_validate_connector_receipt(
        expected_binding=BIND, fetch_json=fetch,
        download_zip=lambda _: pytest.fail("should never download"))
    assert result["reason"] == reason and result["authentic"] is False


def test_wrong_workflow_refuses_without_download():
    bad = _run()
    bad["path"] = ".github/workflows/unrelated.yml"
    fetch, calls = _fetch([], bad)
    result = seam.retrieve_and_validate_connector_receipt(
        expected_binding=BIND, fetch_json=fetch,
        download_zip=lambda _: pytest.fail("should never download"))
    assert result["reason"] == "run-metadata-mismatch:workflow_path" and len(calls) == 1


def test_connector_failure_blocks_without_download():
    def fail(_):
        raise OSError("network")
    result = seam.retrieve_and_validate_connector_receipt(
        expected_binding=BIND, fetch_json=fail,
        download_zip=lambda _: pytest.fail("should never download"))
    assert result["reason"] == "github-run-read-unavailable" and result["authentic"] is False


def test_connector_file_reference_is_not_zip_bytes():
    fetch, _ = _fetch([{"total_count": 1, "artifacts": [_art(999, True)]}])
    result = seam.retrieve_and_validate_connector_receipt(
        expected_binding=BIND, fetch_json=fetch,
        download_zip=lambda _: {"file_uri": "connector-file"})
    assert result["reason"] == "artifact-bytes-unavailable"
