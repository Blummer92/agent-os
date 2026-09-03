"""Bounded GitHub issue-comment transport parsing for Agent OS Scheduler ingress.

This module validates only the low-trust GitHub event envelope for #1203,
#1432, #1454, #1495, #1515, and #1768. A successful parse is transport evidence,
not implementation authorization and not Scheduler admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

INGRESS_SCHEMA_VERSION = "1.0"
MAX_EVENT_BYTES = 1_048_576
MAX_COMMENT_BYTES = 256
_HANDOFF_RE = re.compile(r"executor-handoff:[0-9a-f]{64}", re.ASCII)
_TRIGGER_RE = re.compile(r"/agent-os resume (?P<handoff>executor-handoff:[0-9a-f]{64})", re.ASCII)
_VALIDATION_IDS = (
    "remote-validation-suite",
    "instructional-materials-current-curriculum-suite",
    "semantic-ownership-advisory",
    "ppux-picture-perfect-ts-vitest",
    "eia-paddleocr-runtime-qualification",
)
_DEV_VALIDATE_RE = re.compile(
    r"/agent-os dev-validate (?P<branch>agent/[A-Za-z0-9._/-]{1,180}) "
    r"(?P<sha>[0-9a-f]{40}) (?P<validation_id>"
    + "|".join(re.escape(value) for value in _VALIDATION_IDS)
    + r")",
    re.ASCII,
)
_REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", re.ASCII)
_ACTOR_RE = re.compile(r"[A-Za-z0-9-]{1,39}", re.ASCII)

IngressStatus = Literal["accepted", "blocked", "ignored"]
IngressReason = Literal[
    "accepted-envelope", "accepted-discovery-envelope", "accepted-runtime-inspection-envelope",
    "accepted-dev-validation-envelope", "event-not-created", "pull-request-comment",
    "repository-mismatch", "workflow-rerun", "actor-not-allowed", "actor-evidence-mismatch",
    "malformed-trigger", "invalid-event-envelope",
]

@dataclass(frozen=True, slots=True, kw_only=True)
class IssueCommentIngressResult:
    schema_version: str; status: IngressStatus; reason: IngressReason; repository: str
    issue_number: int | None; comment_id: int | None; actor: str | None
    handoff_id_or_none: str | None; logical_trigger_id_or_none: str | None; run_attempt: int
    dev_validation_branch_or_none: str | None = None
    dev_validation_sha_or_none: str | None = None
    dev_validation_id_or_none: str | None = None
    execution_authorized: Literal[False] = field(default=False, init=False)
    scheduler_invoked: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)
    def to_dict(self) -> dict[str, object]:
        return {"schema_version":self.schema_version,"status":self.status,"reason":self.reason,"repository":self.repository,"issue_number":self.issue_number,"comment_id":self.comment_id,"actor":self.actor,"handoff_id_or_none":self.handoff_id_or_none,"logical_trigger_id_or_none":self.logical_trigger_id_or_none,"run_attempt":self.run_attempt,"dev_validation_branch_or_none":self.dev_validation_branch_or_none,"dev_validation_sha_or_none":self.dev_validation_sha_or_none,"dev_validation_id_or_none":self.dev_validation_id_or_none,"execution_authorized":False,"scheduler_invoked":False,"side_effects_performed":False}

def _logical_trigger_id(repository: str, issue_number: int, handoff_id: str) -> str:
    material = f"{repository}\0{issue_number}\0{handoff_id}".encode("ascii")
    return f"issue-comment-trigger:{hashlib.sha256(material).hexdigest()}"

def _operation_trigger_id(repository: str, issue_number: int, operation: str) -> str:
    material = f"{repository}\0{issue_number}\0{operation}".encode("ascii")
    return f"issue-comment-trigger:{hashlib.sha256(material).hexdigest()}"

def _dev_validation_trigger_id(repository: str, issue_number: int, branch: str, sha: str, validation_id: str) -> str:
    material=f"{repository}\0{issue_number}\0dev-validate\0{branch}\0{sha}\0{validation_id}".encode("ascii")
    return f"issue-comment-trigger:{hashlib.sha256(material).hexdigest()}"

def _result(*,status:IngressStatus,reason:IngressReason,repository:str,run_attempt:int,issue_number:int|None=None,comment_id:int|None=None,actor:str|None=None,handoff_id:str|None=None,operation:str|None=None,dev_validation_branch:str|None=None,dev_validation_sha:str|None=None,dev_validation_id:str|None=None)->IssueCommentIngressResult:
    logical_id=None
    if handoff_id is not None and issue_number is not None: logical_id=_logical_trigger_id(repository,issue_number,handoff_id)
    elif dev_validation_branch is not None and dev_validation_sha is not None and dev_validation_id is not None and issue_number is not None: logical_id=_dev_validation_trigger_id(repository,issue_number,dev_validation_branch,dev_validation_sha,dev_validation_id)
    elif operation is not None and issue_number is not None: logical_id=_operation_trigger_id(repository,issue_number,operation)
    return IssueCommentIngressResult(schema_version=INGRESS_SCHEMA_VERSION,status=status,reason=reason,repository=repository,issue_number=issue_number,comment_id=comment_id,actor=actor,handoff_id_or_none=handoff_id,logical_trigger_id_or_none=logical_id,run_attempt=run_attempt,dev_validation_branch_or_none=dev_validation_branch,dev_validation_sha_or_none=dev_validation_sha,dev_validation_id_or_none=dev_validation_id)

def _valid_dev_branch(branch:str)->bool:
    return branch.startswith("agent/") and branch not in {"agent/","agent/main"} and ".." not in branch and "//" not in branch and not branch.endswith(("/","."))

def admit_issue_comment_event(event:object,*,expected_repository:str,allowed_actor:str,run_attempt:int)->IssueCommentIngressResult:
    if not _REPOSITORY_RE.fullmatch(expected_repository): raise ValueError("expected_repository must use owner/name syntax")
    if not _ACTOR_RE.fullmatch(allowed_actor): raise ValueError("allowed_actor must use GitHub login syntax")
    if type(run_attempt) is not int or run_attempt<1: raise ValueError("run_attempt must be a positive integer")
    if type(event) is not dict:return _result(status="blocked",reason="invalid-event-envelope",repository=expected_repository,run_attempt=run_attempt)
    action=event.get("action");repository=event.get("repository");issue=event.get("issue");comment=event.get("comment");sender=event.get("sender")
    if not all(type(value) is dict for value in (repository,issue,comment,sender)):return _result(status="blocked",reason="invalid-event-envelope",repository=expected_repository,run_attempt=run_attempt)
    repo_name=repository.get("full_name");issue_number=issue.get("number");comment_id=comment.get("id");comment_user=comment.get("user");sender_login=sender.get("login")
    if type(repo_name) is not str or type(issue_number) is not int or issue_number<1 or type(comment_id) is not int or comment_id<1 or type(comment_user) is not dict or type(sender_login) is not str:return _result(status="blocked",reason="invalid-event-envelope",repository=expected_repository,run_attempt=run_attempt)
    comment_login=comment_user.get("login");actor=comment_login if type(comment_login) is str else None
    common=dict(repository=expected_repository,run_attempt=run_attempt,issue_number=issue_number,comment_id=comment_id,actor=actor)
    if action!="created":return _result(status="blocked",reason="event-not-created",**common)
    if "pull_request" in issue:return _result(status="ignored",reason="pull-request-comment",**common)
    if repo_name!=expected_repository:return _result(status="blocked",reason="repository-mismatch",**common)
    if run_attempt!=1:return _result(status="blocked",reason="workflow-rerun",**common)
    if actor!=allowed_actor:return _result(status="blocked",reason="actor-not-allowed",**common)
    if sender_login!=actor:return _result(status="blocked",reason="actor-evidence-mismatch",**common)
    body=comment.get("body")
    if type(body) is not str or len(body.encode("utf-8"))>MAX_COMMENT_BYTES:return _result(status="ignored",reason="malformed-trigger",**common)
    if body=="/agent-os discover":return _result(status="accepted",reason="accepted-discovery-envelope",operation="discover",**common)
    if body=="/agent-os inspect-runtime":return _result(status="accepted",reason="accepted-runtime-inspection-envelope",operation="inspect-runtime",**common)
    dev_match=_DEV_VALIDATE_RE.fullmatch(body)
    if dev_match is not None:
        branch=dev_match.group("branch")
        if not _valid_dev_branch(branch):return _result(status="ignored",reason="malformed-trigger",**common)
        return _result(status="accepted",reason="accepted-dev-validation-envelope",dev_validation_branch=branch,dev_validation_sha=dev_match.group("sha"),dev_validation_id=dev_match.group("validation_id"),**common)
    match=_TRIGGER_RE.fullmatch(body)
    if match is None:return _result(status="ignored",reason="malformed-trigger",**common)
    handoff_id=match.group("handoff")
    if _HANDOFF_RE.fullmatch(handoff_id) is None:return _result(status="ignored",reason="malformed-trigger",**common)
    return _result(status="accepted",reason="accepted-envelope",handoff_id=handoff_id,**common)

def _read_event(path:Path)->object:
    if path.stat().st_size>MAX_EVENT_BYTES:raise ValueError("event payload exceeds byte bound")
    return json.loads(path.read_text(encoding="utf-8"))
def _write_result(path:Path,result:IssueCommentIngressResult)->None:
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result.to_dict(),sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8")
def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--event",type=Path,required=True);parser.add_argument("--repository",required=True);parser.add_argument("--allowed-actor",required=True);parser.add_argument("--run-attempt",type=int,required=True);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args(argv)
    result=admit_issue_comment_event(_read_event(args.event),expected_repository=args.repository,allowed_actor=args.allowed_actor,run_attempt=args.run_attempt);_write_result(args.output,result);print(json.dumps(result.to_dict(),sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
