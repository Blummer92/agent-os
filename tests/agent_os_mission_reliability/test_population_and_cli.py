"""Offline regression tests for frozen input, report completeness, and CLI boundaries."""

import copy
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from enum import Enum

import pytest

from scripts.agent_os_mission_reliability import acquire_mission_records, derive_mission_reliability
from scripts.agent_os_mission_reliability import service
from scripts.agent_os_mission_reliability.args import parse_args
from scripts.agent_os_mission_reliability.cli import main
from scripts.agent_os_mission_reliability.errors import ReadError, ValidationError
from scripts.agent_os_mission_reliability.http_client import JsonPage
from scripts.agent_os_mission_reliability.report import render

STAMP = "2026-11-25T20:00:00Z"
PREFIX = ["--owner", "owner", "--repo", "repo", "--issues"]


@pytest.mark.parametrize("value", ["", "1,,2", ",1", "1,", "0", "-1", "abc", "2147483648", "1," * 100 + "2"])
def test_bad_frozen_population_is_json_without_transport(value, capsys, monkeypatch):
    monkeypatch.setattr("scripts.agent_os_mission_reliability.cli.get_json",
                        lambda *a, **k: pytest.fail("invalid input touched network"))
    assert main([*PREFIX, value]) == 2
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"error"}
    assert out["error"]["field"] == "issues"
    if value in ("", "1,,2", ",1", "1,"):
        assert out["error"]["code"] == "invalid_list"


@pytest.mark.parametrize("value,code", [
    ("1", "invalid_timestamp"), ("1:", "invalid_timestamp"),
    ("1:bad", "invalid_timestamp"), ("1:2026-01-01", "invalid_timestamp"),
    ("1:2026-01-01T12:00:00", "invalid_timestamp"),
    (f"1:{STAMP},1:{STAMP}", "duplicate_admission"),
    (f"2:{STAMP}", "outside_population"), (":x", "invalid_issue"),
    ("", "invalid_list"), (f"1:{STAMP},", "invalid_list"),
])
def test_bad_admission_does_not_emit_report(value, code, capsys, monkeypatch):
    monkeypatch.setattr("scripts.agent_os_mission_reliability.cli.get_json",
                        lambda *a, **k: pytest.fail("invalid admission touched transport"))
    assert main([*PREFIX, "1", "--admitted", value]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == code


def _reader(path, params):
    if path.endswith("/pulls"):
        assert params == {"state": "all", "per_page": 100, "page": 1, "sort": "created", "direction": "desc"}
        return []
    return {"number": int(path.rsplit("/", 1)[1]), "state": "open"}


def test_frozen_order_nonadmission_and_json_shape(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr("scripts.agent_os_mission_reliability.cli.get_json", lambda p, q, **kw: _reader(p, q))
    assert main([*PREFIX, "3,2,3,1", "--admitted", f"2:{STAMP}"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"records", "report"}
    assert out["records"]["frozen_issue_numbers"] == [3, 2, 1]
    assert [x["admitted"] for x in out["records"]["records"]] == [False, True, False]
    assert out["report"]["window"] == {
        "repository": "owner/repo", "issue_numbers": [3, 2, 1], "label": "owner/repo frozen issues 3,2,1",
    }
    assert derive_mission_reliability(out["records"]["records"], window="legacy")["window"] == "legacy"


@pytest.mark.parametrize("numbers,rows", [([1,2],[1]), ([1,2],[1,1]), ([1,2],[1,3]), ([1,2],[2,1]), ([1,2],[True,2])])
def test_report_refuses_incomplete_or_wrong_record_population(numbers, rows, monkeypatch):
    population = parse_args([*PREFIX, "1,2"])
    monkeypatch.setattr(service, "acquire_frozen_records", lambda *_: {
        "repository": "owner/repo", "frozen_issue_numbers": numbers, "records": [{"issue_number": n} for n in rows],
    })
    with pytest.raises(ReadError, match="frozen population") as out:
        service.measure(_reader, population)
    assert out.value.code == "incomplete_population"


def test_provider_issue_and_pr_detail_identity_are_separately_verified():
    with pytest.raises(ReadError) as exc:
        acquire_mission_records(lambda p, q: [] if p.endswith("/pulls") else {"number": 2},
                                owner="owner", repository="repo", issue_numbers=[1])
    assert exc.value.code == "identity_mismatch"
    def reader(path, params):
        if path.endswith("/pulls"):
            return [{"number": 42, "body": "Fixes #1"}]
        return {"number": 44, "merged": True} if "/pulls/" in path else {"number": 1}
    with pytest.raises(ReadError) as exc:
        acquire_mission_records(reader, owner="owner", repository="repo", issue_numbers=[1])
    assert exc.value.code == "identity_mismatch"


def test_http_page_metadata_controls_next_page_and_ceiling():
    pages = []
    def reader(path, params):
        if path.endswith("/pulls"):
            page = params["page"]
            pages.append(page)
            return JsonPage([{"number": page}], page == 1)
        return {"number": 1}
    acquire_mission_records(reader, owner="owner", repository="repo", issue_numbers=[1])
    assert pages == [1, 2]
    with pytest.raises(ReadError) as exc:
        acquire_mission_records(reader, owner="owner", repository="repo", issue_numbers=[1], max_pr_pages=1)
    assert exc.value.code == "incomplete_pr_population"


def test_invalid_record_shapes_and_input_unchanged():
    for bad in (None, {}, [], [None], [{}], [{"issue_number": True}], [{"issue_number": 1, "admitted": True}],
                [{"issue_number": 1, "terminal_state": []}], [{"issue_number": 1, "implementation_prs": {}}]):
        with pytest.raises(ValidationError):
            derive_mission_reliability(bad, window="test")
    with pytest.raises(ValidationError, match="repeat"):
        derive_mission_reliability([{"issue_number": 1}, {"issue_number": 1}], window="test")
    data = [{"issue_number": 2, "admitted": True, "admitted_at": STAMP, "implementation_prs": []}]
    before = copy.deepcopy(data)
    derive_mission_reliability(data, window="test")
    assert before == data


def test_read_failure_and_encoding_do_not_print_a_partial_document(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise ReadError("transport_failure", "Read failed.", "github")
    monkeypatch.setattr("scripts.agent_os_mission_reliability.cli.get_json", fail)
    assert main([*PREFIX, "1"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "transport_failure"
    monkeypatch.setattr("scripts.agent_os_mission_reliability.cli.measure", lambda *_: {"bad": object()})
    assert main([*PREFIX, "1"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "report_encoding"
    class _Status(Enum):
        END = 3
    assert json.loads(render({"state": _Status.END, "date": datetime(2026, 11, 25, tzinfo=timezone.utc)})) == {
        "state": 3, "date": "2026-11-25T00:00:00+00:00",
    }


def test_real_module_cli_no_pythonpath_on_bad_input():
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    p = subprocess.run([sys.executable, "-B", "-m", "scripts.agent_os_mission_reliability", *PREFIX, "1,,2"],
                       env=env, capture_output=True, text=True, check=False)
    assert p.returncode == 2 and not p.stderr
    assert json.loads(p.stdout)["error"]["code"] == "invalid_list"


def test_issue_endpoint_must_not_return_pull_request_shaped_record():
    def reader(path, _):
        return [] if path.endswith("/pulls") else {"number": 1, "pull_request": {}}
    with pytest.raises(ReadError, match="not an issue") as out:
        acquire_mission_records(reader, owner="owner", repository="repo", issue_numbers=[1])
    assert out.value.code == "not_an_issue"


def test_frozen_population_metadata_rejects_boolean_equality(monkeypatch):
    pop = parse_args([*PREFIX, "1"])
    monkeypatch.setattr(service, "acquire_frozen_records", lambda *_: {
        "repository": "owner/repo", "frozen_issue_numbers": [True], "records": [{"issue_number": 1}],
    })
    with pytest.raises(ReadError, match="frozen population"):
        service.measure(_reader, pop)


def test_cli_can_verify_twenty_one_pr_pages_without_abandoning_the_bound(monkeypatch, capsys):
    calls = []
    def reader(path, params, **_):
        if not path.endswith("/pulls"):
            return {"number": 1}
        number = params["page"]
        calls.append(number)
        return JsonPage([{"number": number}], number < 21)
    monkeypatch.setattr("scripts.agent_os_mission_reliability.cli.get_json", reader)
    assert main([*PREFIX, "1"]) == 0
    assert calls == list(range(1,22))
    assert json.loads(capsys.readouterr().out)["records"]["frozen_issue_numbers"] == [1]
