from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

REWRITE_KINDS = {
    "keep", "remove-noise", "replace-sequence", "move-before", "move-after",
    "change-selector", "insert-assertion",
}
_ACTION_ID_RE = re.compile(r"action-(0|[1-9][0-9]*)\Z")

@dataclass(frozen=True)
class RewriteOperation:
    kind: str
    semantic_action_id: str
    source_indexes: tuple[int, ...]
    evidence: tuple[str, ...] = ()
    confidence: str = "unproven"
    output_indexes: tuple[int, ...] = ()
    changes_order: bool = False
    changes_selector: bool = False
    changes_behavior: bool = False

    def __post_init__(self) -> None:
        if self.kind not in REWRITE_KINDS:
            raise ValueError(f"unsupported rewrite kind: {self.kind}")
        if not self.source_indexes:
            raise ValueError("rewrite operation requires source indexes")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_indexes"] = list(self.source_indexes)
        data["evidence"] = list(self.evidence)
        data["output_indexes"] = list(self.output_indexes)
        return data

@dataclass(frozen=True)
class RewriteResult:
    rewritten_recording: dict[str, Any]
    operations: tuple[RewriteOperation, ...]
    provenance: dict[int, tuple[int, ...]]
    warnings: tuple[str, ...]
    semantic_equivalence: str

    def to_dict(self) -> dict[str, Any]:
        return {"rewritten_recording": self.rewritten_recording, "operations": [op.to_dict() for op in self.operations], "provenance": {str(k): list(v) for k, v in self.provenance.items()}, "warnings": list(self.warnings), "semantic_equivalence": self.semantic_equivalence}


def rewrite_replay(payload: dict[str, Any]) -> RewriteResult:
    steps = payload.get("steps")
    if not isinstance(steps, list): raise ValueError("Replay JSON must contain a list at steps[]")
    from .analyzer import analyze_replay
    actions = analyze_replay(payload); rewritten_steps=[]; operations=[]; provenance={}; warnings=[]
    for action_index, action in enumerate(actions):
        source_indexes=action.source_indexes; source_steps=[steps[i] for i in source_indexes]
        if action.kind in {"rename","text_entry"} and len(source_indexes)>1:
            change_steps=[(idx,steps[idx]) for idx in source_indexes if isinstance(steps[idx],dict) and steps[idx].get("type")=="change"]
            if not change_steps:
                warnings.append(f"action-{action_index}: no change step found")
                return RewriteResult(dict(payload),tuple(operations),provenance,tuple(warnings),"rejected")
            _, final_change=change_steps[-1]; output_index=len(rewritten_steps); rewritten_steps.append(dict(final_change)); provenance[output_index]=source_indexes
            operations.append(RewriteOperation("replace-sequence",f"action-{action_index}",source_indexes,action.evidence,"proven",(output_index,)))
            continue
        for source_index, step in zip(source_indexes,source_steps):
            if not isinstance(step,dict): raise ValueError(f"steps[{source_index}] must be an object")
            output_index=len(rewritten_steps); rewritten_steps.append(dict(step)); provenance[output_index]=(source_index,)
            operations.append(RewriteOperation("keep",f"action-{action_index}",(source_index,),action.evidence,"proven",(output_index,)))
    rewritten=dict(payload); rewritten["steps"]=rewritten_steps
    return RewriteResult(rewritten,tuple(operations),provenance,tuple(warnings),"proven")

@dataclass(frozen=True)
class RewriteRequest:
    kind: str
    semantic_action_id: str
    source_indexes: tuple[int, ...]
    evidence: tuple[str, ...] = ()
    replacement_selector: str | None = None
    target_action_id: str | None = None
    def __post_init__(self) -> None:
        if self.kind not in REWRITE_KINDS-{"keep"}: raise ValueError(f"unsupported rewrite request kind: {self.kind}")
        if not self.semantic_action_id: raise ValueError("rewrite request requires semantic action id")
        if not self.source_indexes: raise ValueError("rewrite request requires source indexes")
        if self.kind=="change-selector" and not self.replacement_selector: raise ValueError("change-selector requires replacement selector")
        if self.kind in {"move-before","move-after"} and not self.target_action_id: raise ValueError(f"{self.kind} requires target action id")

def apply_request(payload: dict[str, Any], request: RewriteRequest) -> RewriteResult:
    steps=payload.get("steps")
    if not isinstance(steps,list): raise ValueError("Replay JSON must contain a list at steps[]")
    from .analyzer import analyze_replay
    actions=analyze_replay(payload)
    match=_ACTION_ID_RE.fullmatch(request.semantic_action_id)
    if match is None:
        return RewriteResult(dict(payload),(),{},("unknown semantic action id",),"rejected")
    action_index=int(match.group(1))
    if action_index >= len(actions):
        return RewriteResult(dict(payload),(),{},("unknown semantic action id",),"rejected")
    action=actions[action_index]
    if tuple(request.source_indexes)!=tuple(action.source_indexes): return RewriteResult(dict(payload),(),{},("source indexes do not match semantic action",),"rejected")
    if request.kind=="remove-noise":
        if action.recovery: return RewriteResult(dict(payload),(),{},("recovery behavior cannot be removed as noise",),"rejected")
        if action.instructional: return RewriteResult(dict(payload),(),{},("instructional action cannot be removed as noise",),"rejected")
        if action.kind!="keyboard_noise": return RewriteResult(dict(payload),(),{},("only proven keyboard noise may be removed automatically",),"rejected")
        removed=set(action.source_indexes); rewritten_steps=[dict(step) for index,step in enumerate(steps) if index not in removed]; provenance={}; output_index=0
        for source_index in range(len(steps)):
            if source_index in removed: continue
            provenance[output_index]=(source_index,); output_index+=1
        rewritten=dict(payload); rewritten["steps"]=rewritten_steps
        operation=RewriteOperation("remove-noise",request.semantic_action_id,action.source_indexes,request.evidence or action.evidence,"proven",())
        return RewriteResult(rewritten,(operation,),provenance,(),"proven")
    if request.kind!="change-selector": return RewriteResult(dict(payload),(),{},(f"request kind not implemented safely: {request.kind}",),"unproven")
    replacement=request.replacement_selector
    if replacement is None or replacement not in action.evidence: return RewriteResult(dict(payload),(),{},("replacement selector is not present in recorded evidence",),"rejected")
    if len(action.source_indexes)!=1: return RewriteResult(dict(payload),(),{},("selector change requires one source step",),"rejected")
    source_index=action.source_indexes[0]; source_step=steps[source_index]
    if not isinstance(source_step,dict): raise ValueError(f"steps[{source_index}] must be an object")
    rewritten_steps=[dict(step) for step in steps]; rewritten_step=dict(source_step); rewritten_step["selectors"]=[[replacement]]; rewritten_steps[source_index]=rewritten_step
    rewritten=dict(payload); rewritten["steps"]=rewritten_steps; provenance={index:(index,) for index in range(len(steps))}
    operation=RewriteOperation("change-selector",request.semantic_action_id,action.source_indexes,request.evidence or action.evidence,"proven",(source_index,),changes_selector=True)
    return RewriteResult(rewritten,(operation,),provenance,(),"proven")
