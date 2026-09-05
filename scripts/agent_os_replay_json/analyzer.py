from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

SUPPORTED_TYPES = {
    "setViewport", "navigate", "click", "doubleClick", "change", "keyDown", "keyUp"
}
_KEY_TYPES = {"keyDown", "keyUp"}
_DATA_TESTID_RE = re.compile(r"\[data-testid=(?P<quote>['\"])(?P<value>[^'\"]+)\1\]")


@dataclass(frozen=True)
class SemanticAction:
    kind: str
    source_indexes: tuple[int, ...]
    target: str | None = None
    value: str | None = None
    interaction: str | None = None
    instructional: bool = True
    recovery: bool = False
    fragile: bool = False
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_indexes"] = list(self.source_indexes)
        data["evidence"] = list(self.evidence)
        return data


def _selector_strings(step: dict[str, Any]) -> list[str]:
    selectors = step.get("selectors", []) or []
    if not isinstance(selectors, list):
        return []
    out: list[str] = []
    for chain in selectors:
        if isinstance(chain, list):
            out.extend(part for part in chain if isinstance(part, str))
        elif isinstance(chain, str):
            out.append(chain)
    return out


def _evidence(step: dict[str, Any]) -> tuple[str, ...]:
    evidence = _selector_strings(step)
    if step.get("url"):
        evidence.append(str(step["url"]))
    if "value" in step:
        evidence.append(f"value={step['value']}")
    return tuple(evidence)


def _identity(step: dict[str, Any]) -> str | None:
    selectors = _selector_strings(step)
    for selector in selectors:
        if "folder-asset-card-" in selector:
            start = selector.find("folder-asset-card-")
            end = selector.find("']", start)
            return selector[start:end if end != -1 else None]
        if "file-asset-card-" in selector:
            start = selector.find("file-asset-card-")
            end = selector.find("']", start)
            return selector[start:end if end != -1 else None]
        if "editor-document-title" in selector or "renameInputBox" in selector:
            return "editor-document-title"
        if "organizer-rename-textfield" in selector:
            return "organizer-rename-textfield"
    for selector in selectors:
        match = _DATA_TESTID_RE.search(selector)
        if match:
            return match.group("value")
    return selectors[-1] if selectors else None


def _fragile(evidence: Iterable[str]) -> bool:
    text = " ".join(evidence).lower()
    markers = (
        "urn:aaid:", "x-loading", "search-history", "untitled - ",
        "sp-menu-item-", "x-loading-folder-card", "x-asset-card-wrapper-",
    )
    return any(marker in text for marker in markers)


def _recovery(evidence: Iterable[str]) -> bool:
    text = " ".join(evidence).lower()
    return any(marker in text for marker in (
        "upload-in-progress", "x-loading", "error-dialog", "loading-folder-card"
    ))


def _click_kind(step: dict[str, Any], identity: str | None) -> str:
    text = " ".join(_selector_strings(step)).lower()
    if identity and identity.startswith("folder-asset-card-") and "preview-button-id" not in text:
        return "open_folder"
    if "sidebar-button" in text and "your-stuff" in text:
        return "open_your_stuff"
    if "create-asset-menu-item-folder" in text:
        return "choose_create_folder"
    if "create-asset-menu-item-file" in text:
        return "choose_create_file"
    if "action-item-rename" in text:
        return "choose_rename"
    if "organizer-dialog-submit" in text:
        return "confirm_dialog"
    if "editor-document-title" in text or "renameinputbox" in text:
        return "activate_title"
    return "click"


def _change_value(step: dict[str, Any]) -> str | None:
    if "value" not in step or step["value"] is None:
        return None
    value = step["value"]
    return value if isinstance(value, str) else str(value)


def analyze_replay(payload: dict[str, Any]) -> list[SemanticAction]:
    steps = payload.get("steps")
    if not isinstance(steps, list):
        raise ValueError("Replay JSON must contain a list at steps[]")

    actions: list[SemanticAction] = []
    i = 0
    while i < len(steps):
        step = steps[i]
        if not isinstance(step, dict):
            raise ValueError(f"steps[{i}] must be an object")
        event_type = step.get("type")
        if event_type not in SUPPORTED_TYPES:
            actions.append(SemanticAction(
                kind="unsupported", source_indexes=(i,), instructional=False,
                evidence=_evidence(step), fragile=_fragile(_evidence(step))
            ))
            i += 1
            continue

        evidence = _evidence(step)
        identity = _identity(step)
        recovery = _recovery(evidence)
        fragile = _fragile(evidence)

        if event_type == "setViewport":
            actions.append(SemanticAction(
                kind="replay_infrastructure", source_indexes=(i,), instructional=False,
                evidence=evidence
            ))
            i += 1
            continue

        if event_type == "navigate":
            url = step.get("url")
            actions.append(SemanticAction(
                kind="navigate", source_indexes=(i,),
                target=url if isinstance(url, str) else None,
                fragile=fragile, evidence=evidence
            ))
            i += 1
            continue

        if event_type in {"click", "doubleClick"}:
            actions.append(SemanticAction(
                kind=_click_kind(step, identity), source_indexes=(i,), target=identity,
                interaction=event_type, instructional=not recovery, recovery=recovery,
                fragile=fragile, evidence=evidence
            ))
            i += 1
            continue

        if event_type == "change":
            indexes = [i]
            final_value = _change_value(step)
            target = identity
            combined_evidence = list(evidence)
            j = i + 1
            while j < len(steps):
                nxt = steps[j]
                if not isinstance(nxt, dict):
                    break
                nxt_type = nxt.get("type")
                nxt_identity = _identity(nxt)
                if nxt_type in _KEY_TYPES and (nxt_identity is None or nxt_identity == target):
                    indexes.append(j)
                    combined_evidence.extend(_evidence(nxt))
                    j += 1
                    continue
                if nxt_type == "change" and target is not None and nxt_identity == target:
                    indexes.append(j)
                    final_value = _change_value(nxt)
                    combined_evidence.extend(_evidence(nxt))
                    j += 1
                    continue
                break
            kind = "rename" if target in {"editor-document-title", "organizer-rename-textfield"} else "text_entry"
            actions.append(SemanticAction(
                kind=kind, source_indexes=tuple(indexes), target=target, value=final_value,
                fragile=_fragile(combined_evidence), evidence=tuple(combined_evidence)
            ))
            i = j
            continue

        key = str(step.get("key", ""))
        actions.append(SemanticAction(
            kind="submit" if key == "Enter" and event_type == "keyDown" else "keyboard_noise",
            source_indexes=(i,), target=identity, interaction=event_type,
            instructional=key == "Enter" and event_type == "keyDown",
            evidence=evidence
        ))
        i += 1

    return actions


def semantic_timeline(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [action.to_dict() for action in analyze_replay(payload)]
