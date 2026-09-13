"""Bounded GitHub issue-comment transport parsing for Agent OS Scheduler ingress."""
from __future__ import annotations
import argparse,hashlib,json,re
from dataclasses import dataclass,field
from pathlib import Path
from typing import Literal
INGRESS_SCHEMA_VERSION="1.0";MAX_EVENT_BYTES=1_048_576;MAX_COMMENT_BYTES=256
_HANDOFF_RE=re.compile(r"executor-handoff:[0-9a-f]{64}",re.ASCII);_SOURCE_CAPSULE_RE=re.compile(r"pre-publication-evidence:[0-9a-f]{64}",re.ASCII);_TRIGGER_RE=re.compile(r"/agent-os resume (?P<handoff>executor-handoff:[0-9a-f]{64})",re.ASCII);_ACTIVATION_RE=re.compile(r"/agent-os activate-first-publication (?P<capsule>pre-publication-evidence:[0-9a-f]{64})",re.ASCII);_FIRST_RUN_VALIDATION_RE=re.compile(r"/agent-os validate-first-run (?P<candidate_sha>[0-9a-f]{40})",re.ASCII)
_VALIDATION_IDS=("remote-validation-suite","instructional-materials-current-curriculum-suite","semantic-ownership-advisory","ppux-picture-perfect-ts-vitest","eia-paddleocr-runtime-qualification","issue-scanner-proof")
_DEV_VALIDATE_RE=re.compile(r"/agent-os dev-validate (?P<branch>agent/[A-Za-z0-9._/-]{1,180}) (?P<sha>[0-9a-f]{40}) (?P<validation_id>"+"|".join(re.escape(v) for v in _VALIDATION_IDS)+r")",re.ASCII)
_REPOSITORY_RE=re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",re.ASCII);_ACTOR_RE=re.compile(r"[A-Za-z0-9-]{1,39}",re.ASCII);_NOTION_READ_RE=re.compile(r"/agent-os notion-read (?P<request_id>[a-z0-9][a-z0-9-]{0,62})",re.ASCII)
IngressStatus=Literal["accepted","blocked","ignored"];IngressReason=Literal["accepted-envelope","accepted-discovery-envelope","accepted-runtime-inspection-envelope","accepted-dev-validation-envelope","accepted-first-publication-activation-envelope","accepted-first-run-validation-envelope","accepted-notion-read-envelope","event-not-created","pull-request-comment","repository-mismatch","workflow-rerun","actor-not-allowed","actor-evidence-mismatch","malformed-trigger","invalid-event-envelope"]
@dataclass(frozen=True,slots=True,kw_only=True)
class IssueCommentIngressResult:
 schema_version:str;status:IngressStatus;reason:IngressReason;repository:str;issue_number:int|None;comment_id:int|None;actor:str|None;handoff_id_or_none:str|None;logical_trigger_id_or_none:str|None;run_attempt:int;dev_validation_branch_or_none:str|None=None;dev_validation_sha_or_none:str|None=None;dev_validation_id_or_none:str|None=None;source_capsule_id_or_none:str|None=None;first_run_candidate_sha_or_none:str|None=None;notion_read_request_id_or_none:str|None=None;execution_authorized:Literal[False]=field(default=False,init=False);scheduler_invoked:Literal[False]=field(default=False,init=False);side_effects_performed:Literal[False]=field(default=False,init=False)
 def to_dict(self):return {"schema_version":self.schema_version,"status":self.status,"reason":self.reason,"repository":self.repository,"issue_number":self.issue_number,"comment_id":self.comment_id,"actor":self.actor,"handoff_id_or_none":self.handoff_id_or_none,"logical_trigger_id_or_none":self.logical_trigger_id_or_none,"run_attempt":self.run_attempt,"dev_validation_branch_or_none":self.dev_validation_branch_or_none,"dev_validation_sha_or_none":self.dev_validation_sha_or_none,"dev_validation_id_or_none":self.dev_validation_id_or_none,"source_capsule_id_or_none":self.source_capsule_id_or_none,"first_run_candidate_sha_or_none":self.first_run_candidate_sha_or_none,"notion_read_request_id_or_none":self.notion_read_request_id_or_none,"execution_authorized":False,"scheduler_invoked":False,"side_effects_performed":False}
def _logical_trigger_id(r,i,h):return "issue-comment-trigger:"+hashlib.sha256(f"{r}\0{i}\0{h}".encode("ascii")).hexdigest()
def _operation_trigger_id(r,i,o):return "issue-comment-trigger:"+hashlib.sha256(f"{r}\0{i}\0{o}".encode("ascii")).hexdigest()
def _activation_trigger_id(r,i,c):return "issue-comment-trigger:"+hashlib.sha256(f"{r}\0{i}\0activate-first-publication\0{c}".encode("ascii")).hexdigest()
def _first_run_validation_trigger_id(r,i,s):return "issue-comment-trigger:"+hashlib.sha256(f"{r}\0{i}\0validate-first-run\0{s}".encode("ascii")).hexdigest()
def _notion_read_trigger_id(r,i,q):return "issue-comment-trigger:"+hashlib.sha256(f"{r}\0{i}\0notion-read\0{q}".encode("ascii")).hexdigest()
def _dev_validation_trigger_id(r,i,b,s,v):return "issue-comment-trigger:"+hashlib.sha256(f"{r}\0{i}\0dev-validate\0{b}\0{s}\0{v}".encode("ascii")).hexdigest()
def _result(*,status,reason,repository,run_attempt,issue_number=None,comment_id=None,actor=None,handoff_id=None,operation=None,dev_validation_branch=None,dev_validation_sha=None,dev_validation_id=None,source_capsule_id=None,first_run_candidate_sha=None,notion_read_request_id=None):
 logical=None
 if handoff_id is not None and issue_number is not None:logical=_logical_trigger_id(repository,issue_number,handoff_id)
 elif source_capsule_id is not None and issue_number is not None:logical=_activation_trigger_id(repository,issue_number,source_capsule_id)
 elif first_run_candidate_sha is not None and issue_number is not None:logical=_first_run_validation_trigger_id(repository,issue_number,first_run_candidate_sha)
 elif notion_read_request_id is not None and issue_number is not None:logical=_notion_read_trigger_id(repository,issue_number,notion_read_request_id)
 elif dev_validation_branch is not None and dev_validation_sha is not None and dev_validation_id is not None and issue_number is not None:logical=_dev_validation_trigger_id(repository,issue_number,dev_validation_branch,dev_validation_sha,dev_validation_id)
 elif operation is not None and issue_number is not None:logical=_operation_trigger_id(repository,issue_number,operation)
 return IssueCommentIngressResult(schema_version=INGRESS_SCHEMA_VERSION,status=status,reason=reason,repository=repository,issue_number=issue_number,comment_id=comment_id,actor=actor,handoff_id_or_none=handoff_id,logical_trigger_id_or_none=logical,run_attempt=run_attempt,dev_validation_branch_or_none=dev_validation_branch,dev_validation_sha_or_none=dev_validation_sha,dev_validation_id_or_none=dev_validation_id,source_capsule_id_or_none=source_capsule_id,first_run_candidate_sha_or_none=first_run_candidate_sha,notion_read_request_id_or_none=notion_read_request_id)
def _valid_dev_branch(b):return b.startswith("agent/") and b not in {"agent/","agent/main"} and ".." not in b and "//" not in b and not b.endswith(("/","."))
def _looks_like_notion_id(v):c=v.replace("-","");return len(c)==32 and all(x in "0123456789abcdef" for x in c)
def _valid_notion_read_request_id(q):return 3<=len(q)<=63 and not q.startswith("-") and not q.endswith("-") and "--" not in q and not _looks_like_notion_id(q)
def admit_issue_comment_event(event,*,expected_repository,allowed_actor,run_attempt):
 if not _REPOSITORY_RE.fullmatch(expected_repository):raise ValueError("expected_repository must use owner/name syntax")
 if not _ACTOR_RE.fullmatch(allowed_actor):raise ValueError("allowed_actor must use GitHub login syntax")
 if type(run_attempt)is not int or run_attempt<1:raise ValueError("run_attempt must be a positive integer")
 if type(event)is not dict:return _result(status="blocked",reason="invalid-event-envelope",repository=expected_repository,run_attempt=run_attempt)
 action=event.get("action");repository=event.get("repository");issue=event.get("issue");comment=event.get("comment");sender=event.get("sender")
 if not all(type(v)is dict for v in (repository,issue,comment,sender)):return _result(status="blocked",reason="invalid-event-envelope",repository=expected_repository,run_attempt=run_attempt)
 repo_name=repository.get("full_name");issue_number=issue.get("number");comment_id=comment.get("id");comment_user=comment.get("user");sender_login=sender.get("login")
 if type(repo_name)is not str or type(issue_number)is not int or issue_number<1 or type(comment_id)is not int or comment_id<1 or type(comment_user)is not dict or type(sender_login)is not str:return _result(status="blocked",reason="invalid-event-envelope",repository=expected_repository,run_attempt=run_attempt)
 actor=comment_user.get("login") if type(comment_user.get("login"))is str else None;common=dict(repository=expected_repository,run_attempt=run_attempt,issue_number=issue_number,comment_id=comment_id,actor=actor)
 if action!="created":return _result(status="blocked",reason="event-not-created",**common)
 if "pull_request" in issue:return _result(status="ignored",reason="pull-request-comment",**common)
 if repo_name!=expected_repository:return _result(status="blocked",reason="repository-mismatch",**common)
 if run_attempt!=1:return _result(status="blocked",reason="workflow-rerun",**common)
 if actor!=allowed_actor:return _result(status="blocked",reason="actor-not-allowed",**common)
 if sender_login!=actor:return _result(status="blocked",reason="actor-evidence-mismatch",**common)
 body=comment.get("body")
 if type(body)is not str or len(body.encode("utf-8"))>MAX_COMMENT_BYTES:return _result(status="ignored",reason="malformed-trigger",**common)
 if body=="/agent-os discover":return _result(status="accepted",reason="accepted-discovery-envelope",operation="discover",**common)
 if body=="/agent-os inspect-runtime":return _result(status="accepted",reason="accepted-runtime-inspection-envelope",operation="inspect-runtime",**common)
 m=_FIRST_RUN_VALIDATION_RE.fullmatch(body)
 if m:return _result(status="accepted",reason="accepted-first-run-validation-envelope",first_run_candidate_sha=m.group("candidate_sha"),**common)
 m=_ACTIVATION_RE.fullmatch(body)
 if m:return _result(status="accepted",reason="accepted-first-publication-activation-envelope",source_capsule_id=m.group("capsule"),**common)
 m=_NOTION_READ_RE.fullmatch(body)
 if m:
  q=m.group("request_id")
  if not _valid_notion_read_request_id(q):return _result(status="ignored",reason="malformed-trigger",**common)
  return _result(status="accepted",reason="accepted-notion-read-envelope",notion_read_request_id=q,**common)
 m=_DEV_VALIDATE_RE.fullmatch(body)
 if m:
  b=m.group("branch")
  if not _valid_dev_branch(b):return _result(status="ignored",reason="malformed-trigger",**common)
  return _result(status="accepted",reason="accepted-dev-validation-envelope",dev_validation_branch=b,dev_validation_sha=m.group("sha"),dev_validation_id=m.group("validation_id"),**common)
 m=_TRIGGER_RE.fullmatch(body)
 if m is None:return _result(status="ignored",reason="malformed-trigger",**common)
 return _result(status="accepted",reason="accepted-envelope",handoff_id=m.group("handoff"),**common)
def _read_event(path):
 if path.stat().st_size>MAX_EVENT_BYTES:raise ValueError("event payload exceeds byte bound")
 return json.loads(path.read_text(encoding="utf-8"))
def _write_result(path,result):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result.to_dict(),sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8")
def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("--event",type=Path,required=True);p.add_argument("--repository",required=True);p.add_argument("--allowed-actor",required=True);p.add_argument("--run-attempt",type=int,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args(argv);r=admit_issue_comment_event(_read_event(a.event),expected_repository=a.repository,allowed_actor=a.allowed_actor,run_attempt=a.run_attempt);_write_result(a.output,r);print(json.dumps(r.to_dict(),sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
