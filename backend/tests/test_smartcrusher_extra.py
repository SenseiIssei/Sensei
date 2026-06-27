from __future__ import annotations

import json

from sensei.compression.smartcrusher import SmartCrusher


def test_object_removes_null_and_empty():
    sc = SmartCrusher()
    out = json.loads(sc.compress(json.dumps({"name": "x", "empty": None, "blank": "", "arr": [], "obj": {}})))
    assert out == {"name": "x"}


def test_nested_redundant_keys_removed():
    sc = SmartCrusher()
    out = json.loads(sc.compress(json.dumps({"data": {"name": "x", "_links": {"a": 1}, "url": "u"}})))
    assert "name" in out["data"]
    assert "_links" not in out["data"]
    assert "url" not in out["data"]


def test_long_string_truncated():
    sc = SmartCrusher()
    out = json.loads(sc.compress(json.dumps({"v": "a" * 300})))
    assert len(out["v"]) < 300
    assert "<+" in out["v"]  # truncation marker


def test_nested_homogeneous_array_is_columnar():
    sc = SmartCrusher()
    data = {"users": [{"id": 1, "a": 9, "b": 8}, {"id": 2, "a": 9, "b": 8}, {"id": 3, "a": 9, "b": 8}]}
    out = json.loads(sc.compress(json.dumps(data)))
    assert "k" in out["users"] and "v" in out["users"]
    assert len(out["users"]["v"]) == 3


def test_small_array_compresses_each_item():
    sc = SmartCrusher()
    out = json.loads(sc.compress(json.dumps([{"id": 1, "x": None}, {"id": 2, "x": None}])))
    assert out == [{"id": 1}, {"id": 2}]


def test_invalid_json_passthrough():
    assert SmartCrusher().compress("not json at all") == "not json at all"
