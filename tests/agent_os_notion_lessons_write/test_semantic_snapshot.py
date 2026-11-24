"""Independent offline create-title scan controls; no provider writes."""
from unittest.mock import Mock
import pytest

from scripts.agent_os_notion_lessons_write.admission import AdmittedRequest
from scripts.agent_os_notion_lessons_write.catalog import CONTINUATION_CONSUMER_REQUEST_ID
from scripts.agent_os_notion_lessons_write.writer import execute
from tests.agent_os_notion_lessons_write.test_writer import Client, _prop, page

REQUEST = AdmittedRequest(100, request_id=CONTINUATION_CONSUMER_REQUEST_ID)
MATCH = "Native execution hosts must enforce continuation; emitted continuation metadata alone is insufficient"
OTHER = "Wheel version metadata should preserve original package provenance"

def row(n, title, i):
    v=page()
    v["id"]=f"00000000-0000-0000-0000-{i:012d}"
    v["properties"]["Lesson ID"]["unique_id"]["number"]=n
    v["properties"]["Lesson Learned"]=_prop("Lesson Learned", title)
    return v

def client_for(*pages):
    client=Client()
    client.find_exact = Mock(return_value={"results":[], "has_more":False, "next_cursor":None})
    client.reserve_create = Mock()
    client.create = Mock(side_effect=AssertionError("Notion write should not execute on this test"))
    client.find_create_candidates = Mock(side_effect=pages)
    return client

def snap(rows=(), **kw):
    return {**{"results":list(rows), "has_more":False, "next_cursor":None}, **kw}

def verify_stop(client, expected):
    v=execute(REQUEST,client)
    assert (v["status"],v["reason_code"])==("blocked",expected)
    assert v["write_attempts"]==0 and not v["readback_verified"]
    assert "duplicate_lesson_ids" not in v
    client.reserve_create.assert_not_called()
    client.create.assert_not_called()

@pytest.mark.parametrize("cursor", ["remaining-page", ""])
def test_contradictory_complete_scan_refuses_before_reserving(cursor):
    client=client_for(snap(next_cursor=cursor),snap(next_cursor=cursor))
    verify_stop(client,"incomplete-duplicate-scan")

@pytest.mark.parametrize("n", [0,-1,1_000_000_000,None])
def test_invalid_return_identity_is_never_emitted_as_canonical(n):
    client=client_for(snap([row(n,MATCH,82)]))
    verify_stop(client,"ambiguous-duplicate-scan")

def test_separate_pages_sharing_stable_id_are_ambiguous_even_if_only_one_title_matches():
    client=client_for(snap([row(82,MATCH,82),row(82,OTHER,83)]))
    verify_stop(client,"ambiguous-duplicate-scan")

def test_second_scan_detects_ambiguous_catalog_even_when_first_was_clean():
    client=client_for(snap(),snap([row(82,MATCH,82),row(82,OTHER,83)]))
    verify_stop(client,"ambiguous-duplicate-scan")
    assert client.find_create_candidates.call_count==2

def test_second_scan_late_unique_duplicate_blocks_both_external_operations():
    client=client_for(snap(),snap([row(82,MATCH,82)]))
    result=execute(REQUEST,client)
    assert (result["status"],result["reason_code"])==("blocked","possible-semantic-duplicate")
    assert result["duplicate_lesson_ids"]==["LL-82"]
    assert result["write_attempts"]==0
    client.reserve_create.assert_not_called()
    client.create.assert_not_called()
