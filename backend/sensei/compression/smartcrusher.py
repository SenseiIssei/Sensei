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

        compressed = self._compress_value(data)
        return json.dumps(compressed, separators=(",", ":"), ensure_ascii=False)

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
