from __future__ import annotations

import json

from sensei.compression.smartcrusher import SmartCrusher


def test_object_keeps_null_and_empty():
    """Dropping them changed the data and was still reported as lossless."""
    sc = SmartCrusher()
    data = {"name": "x", "empty": None, "blank": "", "arr": [], "obj": {}}
    assert json.loads(sc.compress(json.dumps(data))) == data


def test_nested_type_and_url_keys_are_kept():
    """They are facts (a record's kind, where it lives), not noise. An earlier
    version dropped every nested `type`, `url`, `href`, `self` and `_links`
    without a marker."""
    sc = SmartCrusher()
    out = json.loads(
        sc.compress(
            json.dumps({"data": {"name": "x", "_links": {"a": 1}, "url": "u", "type": "t"}})
        )
    )
    assert out == {"data": {"name": "x", "_links": {"a": 1}, "url": "u", "type": "t"}}


def test_long_string_is_kept_whole():
    """No silent truncation: a 300-character value used to come back as 200
    characters and `<+100c>`, with nothing to retrieve it by."""
    sc = SmartCrusher()
    value = "word " * 60
    out = json.loads(sc.compress(json.dumps({"v": value})))
    assert out["v"] == value


def test_nested_homogeneous_array_is_a_table():
    sc = SmartCrusher()
    data = {
        "users": [{"id": 1, "a": 9, "b": 8}, {"id": 2, "a": 9, "b": 8}, {"id": 3, "a": 9, "b": 8}]
    }
    out = sc.compress(json.dumps(data))
    head, table = out.split("\n", 1)
    assert json.loads(head) == {"users": "<@csv users>"}
    assert table.startswith("@csv users rows=3 const(a=9,b=8) cols=id")
    assert table.splitlines()[1:] == ["1", "2", "3"]


def test_small_array_compresses_each_item():
    sc = SmartCrusher()
    data = [{"id": 1, "x": None}, {"id": 2, "x": None}]
    assert json.loads(sc.compress(json.dumps(data))) == data


def test_invalid_json_passthrough():
    assert SmartCrusher().compress("not json at all") == "not json at all"
