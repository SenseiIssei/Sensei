from __future__ import annotations

import json
import re
from typing import Any


class SmartCrusher:
    """Compress JSON content by removing redundancy while preserving semantics.

    Inspired by Headroom's SmartCrusher — handles arrays of dicts, nested
    objects, and mixed types. Strategies:
    - Extract shared keys from arrays of homogeneous dicts into a schema header
    - Shorten long string values via truncation with CCR retrieval markers
    - Remove null/empty values
    - Collapse repeated structures
    """

    # Keys that are commonly redundant in tool outputs
    REDUNDANT_KEYS = {"_links", "self", "href", "type", "url"}

    # Max value length before truncation
    MAX_VALUE_LEN = 200

    def compress(self, json_str: str) -> str:
        """Compress a JSON string."""
        try:
            data = json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            return json_str

        # Biggest win: a homogeneous array of dicts (the shape of almost every
        # list / search / tool output) renders far cheaper as a CSV-schema table
        # than as JSON — no repeated keys, quotes, or per-row braces. Lossless.
        if isinstance(data, list) and self._is_table(data):
            return self._to_csv_schema(data)

        compressed = self._compress_value(data)
        return json.dumps(compressed, separators=(",", ":"), ensure_ascii=False)

    # ─── CSV-schema tabular compaction (lossless) ────────────────────────────

    def _is_table(self, lst: list) -> bool:
        """True if `lst` is a homogeneous array of dicts worth tabulating."""
        if len(lst) < 3 or not all(isinstance(x, dict) for x in lst):
            return False
        common = set.intersection(*(set(d.keys()) for d in lst))
        return len(common) >= 2

    def _to_csv_schema(self, lst: list[dict]) -> str:
        """Render a homogeneous dict array as a compact CSV-schema table.

        Format::

            @csv const(k=v,...) cols=c1,c2,... extra(k=v,...)
            v1,v2,...
            ...

        Constant columns (same value in every row) are hoisted into ``const(...)``
        once instead of repeated per row; keys present in only some rows are
        summarised in ``extra(...)``. Fully reversible to the original records.
        """
        keys = sorted(set.intersection(*(set(d.keys()) for d in lst)))
        rows = [[self._scalar(d.get(k)) for k in keys] for d in lst]

        const: dict[str, str] = {}
        var_idx: list[int] = []
        for ci, key in enumerate(keys):
            if len({r[ci] for r in rows}) == 1:
                const[key] = rows[0][ci]
            else:
                var_idx.append(ci)

        extra: dict[str, str] = {}
        for d in lst:
            for k, v in d.items():
                if k not in keys and k not in extra:
                    extra[k] = self._scalar(v)

        header = "@csv"
        if const:
            header += " const(" + ",".join(f"{k}={self._csv_field(v)}" for k, v in const.items()) + ")"
        header += " cols=" + ",".join(self._csv_field(keys[ci]) for ci in var_idx)
        if extra:
            header += " extra(" + ",".join(f"{k}={self._csv_field(v)}" for k, v in extra.items()) + ")"

        lines = [header]
        for r in rows:
            lines.append(",".join(self._csv_field(r[ci]) for ci in var_idx))
        return "\n".join(lines)

    def _scalar(self, value: Any) -> str:
        """Normalize a JSON value to a single CSV cell string."""
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return self._compress_string(value)
        # Nested object / array — keep as compact JSON inside the cell.
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _csv_field(s: str) -> str:
        """CSV-escape a field (RFC4180-ish): quote if it has a comma, quote, or newline."""
        if any(c in s for c in (",", '"', "\n", "\r")):
            return '"' + s.replace('"', '""') + '"'
        return s

    def _compress_value(self, value: Any, depth: int = 0) -> Any:
        if isinstance(value, dict):
            return self._compress_dict(value, depth)
        if isinstance(value, list):
            return self._compress_list(value, depth)
        if isinstance(value, str):
            return self._compress_string(value)
        return value

    def _compress_dict(self, d: dict, depth: int) -> dict:
        result = {}
        for key, value in d.items():
            # Skip redundant keys at deeper levels
            if depth > 0 and key in self.REDUNDANT_KEYS:
                continue
            # Skip null/empty values
            if value is None or value == "" or value == [] or value == {}:
                continue
            result[key] = self._compress_value(value, depth + 1)
        return result

    def _compress_list(self, lst: list, depth: int) -> list | dict:
        if not lst:
            return []

        # Check if all items are dicts with similar keys
        if all(isinstance(item, dict) for item in lst) and len(lst) > 2:
            return self._compress_dict_array(lst, depth)

        # Compress each item
        return [self._compress_value(item, depth + 1) for item in lst]

    def _compress_dict_array(self, lst: list[dict], depth: int) -> dict:
        """Compress an array of homogeneous dicts by extracting a schema."""
        # Find common keys
        all_keys = [set(d.keys()) for d in lst]
        common_keys = set.intersection(*all_keys) if all_keys else set()

        if len(common_keys) < 2:
            # Not homogeneous enough — just compress each item
            return [self._compress_dict(d, depth + 1) for d in lst]

        # Build columnar representation: {keys: [...], rows: [[v1,v2,...], ...]}
        key_list = sorted(common_keys)
        rows = []
        for item in lst:
            row = [self._compress_value(item.get(k), depth + 1) for k in key_list]
            rows.append(row)

        # Include any extra keys that aren't common
        extra = {}
        for item in lst:
            for k, v in item.items():
                if k not in common_keys and k not in extra:
                    extra[k] = self._compress_value(v, depth + 1)

        result = {"k": key_list, "v": rows}
        if extra:
            result["x"] = extra
        return result

    def _compress_string(self, s: str) -> str:
        """Truncate long strings."""
        if len(s) > self.MAX_VALUE_LEN:
            return s[: self.MAX_VALUE_LEN] + f"…<+{len(s) - self.MAX_VALUE_LEN}c>"
        return s
