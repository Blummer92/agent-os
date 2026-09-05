from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import re
from typing import Any

REWRITE_KINDS = {
    "keep",
    "remove-noise",
    "replace-sequence",
    "move-before",
    "move-after",
    "change-selector",
    "insert-assertion",
}
REWRITE_CONFIDENCE_STATES = {"proven", "unproven"}
SEMANTIC_EQUIVALENCE_STATES = {"proven", "unproven", "rejected"}

_ACTION_ID_RE = re.compile(r"action-(0|[1-9][0-9]*)\Z")


def _validate_source_indexes(source_indexes: tuple[int, ...], owner: str) -> None:
    if not source_indexes:
        raise ValueError(f"{owner} requires source indexes")
    if any(type(index) is not int or index < 0 for index in source_indexes):
        raise ValueError(f"{owner} source indexes must be exact nonnegative integers")
    if tuple(sorted(set(source_indexes))) != source_indexes:
        raise ValueError(f"{owner} source indexes must be unique and increasing")


def _isolated_recording(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a result payload that cannot alias mutable caller structures."""

    return deepcopy(payload)


def _selector_evidence(
    steps: list[Any], source_indexes: tuple[int, ...]
) -> tuple[str, ...]:
    selectors: list[str] = []
    for source_index in source_indexes:
        step = steps[source_index]
        if not isinstance(step, dict):
            continue
        raw_selectors = step.get("selectors", []) or []
        if not isinstance(raw_selectors, list):
            continue
        for chain in raw_selectors:
            if isinstance(chain, list):
                selectors.extend(part for part in chain if isinstance(part, str))
            elif isinstance(chain, str):
                selectors.append(chain)
    return tuple(selectors)


def _request_evidence_is_recorded(
    request_evidence: tuple[str, ...], recorded_evidence: tuple[str, ...]
) -> bool:
    return not request_evidence or set(request_evidence).issubset(recorded_evidence)


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
        _validate_source_indexes(self.source_indexes, "rewrite operation")
        if self.confidence not in REWRITE_CONFIDENCE_STATES:
            raise ValueError(f"unsupported rewrite confidence: {self.confidence}")

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

    def __post_init__(self) -> None:
        if self.semantic_equivalence not in SEMANTIC_EQUIVALENCE_STATES:
            raise ValueError(
                f"unsupported semantic equivalence: {self.semantic_equivalence}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rewritten_recording": self.rewritten_recording,
            "operations": [op.to_dict() for op in self.operations],
            "provenance": {str(k): list(v) for k, v in self.provenance.items()},
            "warnings": list(self.warnings),
            "semantic_equivalence": self.semantic_equivalence,
        }


def rewrite_replay(payload: dict[str, Any]) -> RewriteResult:
    steps = payload.get("steps")
    if not isinstance(steps, list):
        raise ValueError("Replay JSON must contain a list at steps[]")

    from .analyzer import analyze_replay

    actions = analyze_replay(payload)
    rewritten_steps: list[dict[str, Any]] = []
    operations: list[RewriteOperation] = []
    provenance: dict[int, tuple[int, ...]] = {}
    warnings: list[str] = []

    for action_index, action in enumerate(actions):
        source_indexes = action.source_indexes
        source_steps = [steps[i] for i in source_indexes]

        if action.kind in {"rename", "text_entry"} and len(source_indexes) > 1:
            change_steps = [
                (idx, steps[idx])
                for idx in source_indexes
                if isinstance(steps[idx], dict) and steps[idx].get("type") == "change"
            ]
            if not change_steps:
                warnings.append(f"action-{action_index}: no change step found")
                return RewriteResult(
                    rewritten_recording=_isolated_recording(payload),
                    operations=tuple(operations),
                    provenance=provenance,
                    warnings=tuple(warnings),
                    semantic_equivalence="rejected",
                )

            _, final_change = change_steps[-1]
            output_index = len(rewritten_steps)
            rewritten_steps.append(dict(final_change))
            provenance[output_index] = source_indexes
            operations.append(
                RewriteOperation(
                    kind="replace-sequence",
                    semantic_action_id=f"action-{action_index}",
                    source_indexes=source_indexes,
                    evidence=action.evidence,
                    confidence="proven",
                    output_indexes=(output_index,),
                )
            )
            continue

        for source_index, step in zip(source_indexes, source_steps):
            if not isinstance(step, dict):
                raise ValueError(f"steps[{source_index}] must be an object")
            output_index = len(rewritten_steps)
            rewritten_steps.append(dict(step))
            provenance[output_index] = (source_index,)
            operations.append(
                RewriteOperation(
                    kind="keep",
                    semantic_action_id=f"action-{action_index}",
                    source_indexes=(source_index,),
                    evidence=action.evidence,
                    confidence="proven",
                    output_indexes=(output_index,),
                )
            )

    rewritten = dict(payload)
    rewritten["steps"] = rewritten_steps

    return RewriteResult(
        rewritten_recording=rewritten,
        operations=tuple(operations),
        provenance=provenance,
        warnings=tuple(warnings),
        semantic_equivalence="proven",
    )


@dataclass(frozen=True)
class RewriteRequest:
    kind: str
    semantic_action_id: str
    source_indexes: tuple[int, ...]
    evidence: tuple[str, ...] = ()
    replacement_selector: str | None = None
    target_action_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in REWRITE_KINDS - {"keep"}:
            raise ValueError(f"unsupported rewrite request kind: {self.kind}")
        if not self.semantic_action_id:
            raise ValueError("rewrite request requires semantic action id")
        _validate_source_indexes(self.source_indexes, "rewrite request")
        if self.kind == "change-selector" and not self.replacement_selector:
            raise ValueError("change-selector requires replacement selector")
        if self.kind in {"move-before", "move-after"} and not self.target_action_id:
            raise ValueError(f"{self.kind} requires target action id")


def _rejected(payload: dict[str, Any], warning: str) -> RewriteResult:
    return RewriteResult(
        rewritten_recording=_isolated_recording(payload),
        operations=(),
        provenance={},
        warnings=(warning,),
        semantic_equivalence="rejected",
    )


def _unproven(payload: dict[str, Any], warning: str) -> RewriteResult:
    return RewriteResult(
        rewritten_recording=_isolated_recording(payload),
        operations=(),
        provenance={},
        warnings=(warning,),
        semantic_equivalence="unproven",
    )


def apply_request(
    payload: dict[str, Any],
    request: RewriteRequest,
) -> RewriteResult:
    steps = payload.get("steps")
    if not isinstance(steps, list):
        raise ValueError("Replay JSON must contain a list at steps[]")

    from .analyzer import analyze_replay

    actions = analyze_replay(payload)

    match = _ACTION_ID_RE.fullmatch(request.semantic_action_id)
    if match is None:
        return _rejected(payload, "unknown semantic action id")

    action_index = int(match.group(1))
    if action_index >= len(actions):
        return _rejected(payload, "unknown semantic action id")
    action = actions[action_index]

    if tuple(request.source_indexes) != tuple(action.source_indexes):
        return _rejected(payload, "source indexes do not match semantic action")

    selector_evidence = (
        _selector_evidence(steps, action.source_indexes)
        if request.kind == "change-selector"
        else ()
    )
    applicable_evidence = (
        selector_evidence if request.kind == "change-selector" else action.evidence
    )
    if not _request_evidence_is_recorded(request.evidence, applicable_evidence):
        warning = (
            "request evidence is not present in recorded selector evidence"
            if request.kind == "change-selector"
            else "request evidence is not present in recorded evidence"
        )
        return _rejected(payload, warning)

    if request.kind == "remove-noise":
        if action.recovery:
            return _rejected(payload, "recovery behavior cannot be removed as noise")
        if action.instructional:
            return _rejected(payload, "instructional action cannot be removed as noise")
        if action.kind != "keyboard_noise":
            return _rejected(payload, "only proven keyboard noise may be removed automatically")

        removed = set(action.source_indexes)
        rewritten_steps = [
            dict(step) for index, step in enumerate(steps) if index not in removed
        ]
        provenance = {}
        output_index = 0
        for source_index in range(len(steps)):
            if source_index in removed:
                continue
            provenance[output_index] = (source_index,)
            output_index += 1

        rewritten = dict(payload)
        rewritten["steps"] = rewritten_steps

        operation = RewriteOperation(
            kind="remove-noise",
            semantic_action_id=request.semantic_action_id,
            source_indexes=action.source_indexes,
            evidence=request.evidence or action.evidence,
            confidence="proven",
            output_indexes=(),
        )

        return RewriteResult(
            rewritten_recording=rewritten,
            operations=(operation,),
            provenance=provenance,
            warnings=(),
            semantic_equivalence="proven",
        )

    if request.kind != "change-selector":
        return _unproven(payload, f"request kind not implemented safely: {request.kind}")

    replacement = request.replacement_selector
    if replacement is None or replacement not in selector_evidence:
        return _rejected(
            payload,
            "replacement selector is not present in recorded selector evidence",
        )

    if len(action.source_indexes) != 1:
        return _rejected(payload, "selector change requires one source step")

    source_index = action.source_indexes[0]
    source_step = steps[source_index]
    if not isinstance(source_step, dict):
        raise ValueError(f"steps[{source_index}] must be an object")

    rewritten_steps = [dict(step) for step in steps]
    rewritten_step = dict(source_step)
    rewritten_step["selectors"] = [[replacement]]
    rewritten_steps[source_index] = rewritten_step

    rewritten = dict(payload)
    rewritten["steps"] = rewritten_steps

    provenance = {index: (index,) for index in range(len(steps))}
    operation = RewriteOperation(
        kind="change-selector",
        semantic_action_id=request.semantic_action_id,
        source_indexes=action.source_indexes,
        evidence=request.evidence or selector_evidence,
        confidence="proven",
        output_indexes=(source_index,),
        changes_selector=True,
    )

    return RewriteResult(
        rewritten_recording=rewritten,
        operations=(operation,),
        provenance=provenance,
        warnings=(),
        semantic_equivalence="proven",
    )
