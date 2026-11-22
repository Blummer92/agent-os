import pytest
import yaml

from reusable_capability_registry.reader import _UniqueKeySafeLoader


def _load(source):
    return yaml.load(source, Loader=_UniqueKeySafeLoader)


def test_nested_merges_use_earliest_source_and_allow_authored_override():
    document = _load("""
defaults: &defaults {summary: inherited, enabled: true}
left: &left {<<: *defaults, summary: first}
right: &right {summary: second, enabled: false, description: extra}
merged: {<<: [*left, *right], description: explicit}
again: {<<: [*left, *right]}
""")
    assert document["merged"] == {
        "summary": "first", "enabled": True, "description": "explicit",
    }
    assert document["again"] == {
        "summary": "first", "enabled": True, "description": "extra",
    }
    assert document["left"] == {"summary": "first", "enabled": True}


@pytest.mark.parametrize("source", [
    "merged: {<<: {summary: first, summary: second}}",
    "merged: {<<: [{summary: first}, {name: one, name: two}]}",
    "merged: {<<: [{<<: {name: one, name: two}}, {summary: second}]}",
])
def test_duplicates_in_inline_merge_maps_are_not_inherited_overrides(source):
    with pytest.raises(yaml.YAMLError, match="duplicate YAML mapping key"):
        _load(source)


def test_nonmapping_merge_source_fails_as_yaml_error():
    with pytest.raises(yaml.YAMLError, match="expected a mapping"):
        _load("merged: {<<: [item]}")
