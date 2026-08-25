from __future__ import annotations

import json
from pathlib import Path

from workflow_scheduler.governance.github_issue_comment_ingress import admit_issue_comment_event, main

REPOSITORY = "Blummer92/agent-os"
ACTOR = "Blummer92"
HANDOFF = "executor-handoff:" + "a" * 64


def event(body: str, *, action: str = "created", actor: str = ACTOR) -> dict[str, object]:
    return {"action":action,"repository":{"full_name":REPOSITORY},"issue":{"number":1203},"comment":{"id":9981,"body":body,"user":{"login":actor}},"sender":{"login":actor}}


def admit(payload: object, *, run_attempt: int = 1):
    return admit_issue_comment_event(payload,expected_repository=REPOSITORY,allowed_actor=ACTOR,run_attempt=run_attempt)


def test_exact_trigger_is_accepted_but_never_authorizes_or_invokes() -> None:
    result=admit(event(f"/agent-os resume {HANDOFF}"));assert result.status=="accepted";assert result.reason=="accepted-envelope";assert result.handoff_id_or_none==HANDOFF;assert result.logical_trigger_id_or_none is not None;assert result.execution_authorized is False;assert result.scheduler_invoked is False;assert result.side_effects_performed is False


def test_extra_tokens_are_rejected() -> None: assert (lambda r:(r.status,r.reason))(admit(event(f"/agent-os resume {HANDOFF} --force")))==("ignored","malformed-trigger")
def test_shell_syntax_cannot_enter_the_identifier() -> None:
    r=admit(event(f"/agent-os resume {HANDOFF}; rm -rf /"));assert (r.status,r.reason)==("ignored","malformed-trigger");assert r.handoff_id_or_none is None
def test_unauthorized_actor_is_blocked() -> None: assert (lambda r:(r.status,r.reason))(admit(event(f"/agent-os resume {HANDOFF}",actor="mallory")))==("blocked","actor-not-allowed")
def test_sender_and_comment_actor_must_match() -> None:
    p=event(f"/agent-os resume {HANDOFF}");p["sender"]={"login":"mallory"};r=admit(p);assert (r.status,r.reason)==("blocked","actor-evidence-mismatch")
def test_rerun_is_not_executable_transport_authority() -> None: assert (lambda r:(r.status,r.reason))(admit(event(f"/agent-os resume {HANDOFF}"),run_attempt=2))==("blocked","workflow-rerun")
def test_edited_event_is_blocked() -> None: assert (lambda r:(r.status,r.reason))(admit(event(f"/agent-os resume {HANDOFF}",action="edited")))==("blocked","event-not-created")
def test_pull_request_comment_is_ignored() -> None:
    p=event(f"/agent-os resume {HANDOFF}");p["issue"]["pull_request"]={"url":"https://example.invalid/pr/1"};r=admit(p);assert (r.status,r.reason)==("ignored","pull-request-comment")
def test_repository_mismatch_is_blocked() -> None:
    p=event(f"/agent-os resume {HANDOFF}");p["repository"]={"full_name":"someone/else"};r=admit(p);assert (r.status,r.reason)==("blocked","repository-mismatch")
def test_duplicate_comments_share_one_logical_trigger_identity() -> None:
    a=event(f"/agent-os resume {HANDOFF}");b=event(f"/agent-os resume {HANDOFF}");b["comment"]["id"]=9982;assert admit(a).logical_trigger_id_or_none==admit(b).logical_trigger_id_or_none
def test_different_handoffs_have_different_logical_trigger_identities() -> None:
    assert admit(event(f"/agent-os resume {HANDOFF}")).logical_trigger_id_or_none!=admit(event("/agent-os resume executor-handoff:"+"b"*64)).logical_trigger_id_or_none
def test_result_never_copies_comment_body() -> None:
    body=f"/agent-os resume {HANDOFF}";assert body not in json.dumps(admit(event(body)).to_dict(),sort_keys=True)


def test_cli_writes_bounded_canonical_json(tmp_path: Path) -> None:
    ep=tmp_path/"event.json";op=tmp_path/"out"/"transport.json";ep.write_text(json.dumps(event(f"/agent-os resume {HANDOFF}")),encoding="utf-8");assert main(["--event",str(ep),"--repository",REPOSITORY,"--allowed-actor",ACTOR,"--run-attempt","1","--output",str(op)])==0;p=json.loads(op.read_text(encoding="utf-8"));assert p["status"]=="accepted";assert p["execution_authorized"] is False;assert p["scheduler_invoked"] is False;assert p["side_effects_performed"] is False


def test_exact_discovery_trigger_is_accepted_without_handoff_authority() -> None:
    r=admit(event("/agent-os discover"));assert r.status=="accepted";assert r.reason=="accepted-discovery-envelope";assert r.handoff_id_or_none is None;assert r.logical_trigger_id_or_none is not None;assert r.execution_authorized is False;assert r.scheduler_invoked is False;assert r.side_effects_performed is False
def test_discovery_trigger_rejects_arguments_and_fake_handoff_text() -> None:
    r=admit(event(f"/agent-os discover {HANDOFF}"));assert (r.status,r.reason)==("ignored","malformed-trigger");assert r.handoff_id_or_none is None
def test_duplicate_discovery_comments_share_logical_identity() -> None:
    a=event("/agent-os discover");b=event("/agent-os discover");b["comment"]["id"]=9982;assert admit(a).logical_trigger_id_or_none==admit(b).logical_trigger_id_or_none


def test_exact_runtime_inspection_trigger_is_accepted_and_non_authorizing() -> None:
    r=admit(event("/agent-os inspect-runtime"));assert r.status=="accepted";assert r.reason=="accepted-runtime-inspection-envelope";assert r.handoff_id_or_none is None;assert r.logical_trigger_id_or_none is not None;assert r.execution_authorized is False;assert r.scheduler_invoked is False;assert r.side_effects_performed is False


def test_runtime_inspection_rejects_arguments_whitespace_and_handoff() -> None:
    for body in ("/agent-os inspect-runtime "," /agent-os inspect-runtime",f"/agent-os inspect-runtime {HANDOFF}","/agent-os inspect-runtime; whoami"):
        r=admit(event(body));assert (r.status,r.reason)==("ignored","malformed-trigger");assert r.handoff_id_or_none is None


def test_duplicate_runtime_inspection_comments_share_logical_identity() -> None:
    a=event("/agent-os inspect-runtime");b=event("/agent-os inspect-runtime");b["comment"]["id"]=9982;assert admit(a).logical_trigger_id_or_none==admit(b).logical_trigger_id_or_none
