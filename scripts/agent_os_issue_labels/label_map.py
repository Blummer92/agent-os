from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class LabelMap:
    base_labels: list[str]
    fields: dict[str, Any]
    rules: dict[str, Any] = field(default_factory=dict)


def load_label_map(path: str | Path) -> LabelMap:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("label map must be a YAML mapping")
    fields = data.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise ValueError("label map must define fields")
    base_labels = data.get("base_labels", [])
    if not isinstance(base_labels, list):
        raise ValueError("label map base_labels must be a list")
    return LabelMap(
        base_labels=[str(label) for label in base_labels],
        fields=fields,
        rules=dict(data.get("rules") or {}),
    )


def expected_labels(metadata: dict[str, list[str]], label_map: LabelMap) -> tuple[set[str], list[str]]:
    labels = set(label_map.base_labels)
    unknown: list[str] = []
    for field, config in label_map.fields.items():
        values = metadata.get(field, [])
        mapping = (config or {}).get("values", {})
        for value in values:
            if value not in mapping:
                unknown.append(f"{field}={value}")
                continue
            labels.update(str(label) for label in mapping[value].get("labels", []))
    return labels, unknown
