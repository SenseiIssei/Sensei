"""YAML, TOML and INI configuration.

A config file an agent read from disk is a file it may edit next, so the
router hands this compressor only config that is *not* an edit target (pasted
into a prompt, returned by an API). There it removes what a reader does not
need to reason about the values:

- comment lines and blank lines, counted into one marker (the comments are
  in the CCR store, byte-exact);
- trailing whitespace.

Keys, values, nesting and order are untouched.
"""

from __future__ import annotations

import re

from sensei.compression.markers import Context, plural

_YAML_KEY = re.compile(r"^\s*(?:- )?[\w.\"'-]+\s*:(?:\s|$)")
_TOML_TABLE = re.compile(r"^\s*\[\[?[\w.\"' -]+\]\]?\s*(?:#.*)?$")
_KV_EQ = re.compile(r"^\s*[\w.\"'-]+\s*=\s*\S")
_COMMENT = re.compile(r"^\s*(?:#|;)")


def detect(text: str) -> bool:
    lines = [ln for ln in text.split("\n", 200)[:200] if ln.strip() and not _COMMENT.match(ln)]
    if len(lines) < 5:
        return False
    yaml = sum(1 for ln in lines if _YAML_KEY.match(ln) or ln.lstrip().startswith("- "))
    toml = sum(1 for ln in lines if _TOML_TABLE.match(ln) or _KV_EQ.match(ln))
    has_table = any(_TOML_TABLE.match(ln) for ln in lines)
    if has_table and toml >= len(lines) * 0.7:
        return True
    return yaml >= len(lines) * 0.8 and any(_YAML_KEY.match(ln) for ln in lines)


class ConfigCompressor:
    def compress(self, text: str, ctx: Context | None = None) -> str:
        ctx = ctx or Context()
        out: list[str] = []
        comments = 0
        for line in text.split("\n"):
            if _COMMENT.match(line):
                comments += 1
                continue
            if not line.strip():
                continue
            out.append(line.rstrip())
        if comments:
            out.append(ctx.mark(f"{plural(comments, 'comment line')} omitted", comments))
        return "\n".join(out)
