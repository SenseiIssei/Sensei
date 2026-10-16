from __future__ import annotations

import json
import math
import re
import statistics
from itertools import pairwise
from typing import Any

from sensei.compression import dense, relevance
from sensei.compression.markers import Context, plural

# The Rust accelerator (rust/sensei_core) still exports `csv_schema`, but that
# renders the earlier lossy table (strings cut at 200 characters, one sample
# value per optional column). This module no longer calls it: an accelerator
# that returns different bytes is not an accelerator.

_RAW_KEY = re.compile(r"^[A-Za-z_][\w.-]*$")
_NOT_RAW_START = set(' \t"[{')
_ROW_UNSAFE = set(',"\n\r')
_HEADER_UNSAFE = set(',"\n\r()=')


def _is_json_scalar_text(s: str) -> bool:
    if s in ("true", "false", "null"):
        return True
    try:
        float(s)
    except ValueError:
        return s.lower() in ("nan", "infinity", "-infinity")
    return True


def _cell(value: Any, header: bool = False) -> str:
    """One table cell. Raw when unambiguous, JSON otherwise.

    An empty cell means the key is absent from that row; a JSON ``null`` is
    written as ``null``. Nothing is dropped: an earlier version removed null
    and empty values and still called the result lossless.
    """
    if value is _MISSING:
        return ""
    if value is None:
        return "null"
    if isinstance(value, str):
        unsafe = _HEADER_UNSAFE if header else _ROW_UNSAFE
        if (
            value
            and value[0] not in _NOT_RAW_START
            and value[-1] not in " \t"
            and not any(c in unsafe for c in value)
            and not _is_json_scalar_text(value)
        ):
            return value
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _key(k: str) -> str:
    return k if _RAW_KEY.match(k) else json.dumps(k, ensure_ascii=False)


_decoder = json.JSONDecoder()


def _read_cell(s: str, i: int, stops: str) -> tuple[Any, int, bool]:
    """Parse one cell at ``s[i]``; return (value, next index, present)."""
    if i < len(s) and s[i] in '"[{':
        value, end = _decoder.raw_decode(s, i)
        return value, end, True
    j = i
    while j < len(s) and s[j] not in stops:
        j += 1
    tok = s[i:j]
    if tok == "":
        return None, j, False
    if _is_json_scalar_text(tok):
        return json.loads(tok), j, True
    return tok, j, True


def decode_table(text: str) -> list[dict[str, Any]]:
    """Inverse of :meth:`SmartCrusher.table` (for lossless tables)."""
    lines = text.split("\n")
    header = lines[0]
    if not header.startswith("@csv "):
        raise ValueError("not a table")
    i = 5
    const: dict[str, Any] = {}
    cols: list[str] = []
    while i < len(header):
        if header.startswith("rows=", i):
            j = header.find(" ", i)
            i = len(header) if j < 0 else j + 1
            continue
        if header.startswith("const(", i):
            i += 6
            while header[i] != ")":
                key, i, _ = _read_cell(header, i, "=")
                i += 1  # '='
                value, i, present = _read_cell(header, i, ",)")
                const[str(key)] = value if present else None
                if header[i] == ",":
                    i += 1
            i += 2  # ') '
            continue
        if header.startswith("cols=", i):
            i += 5
            while i < len(header):
                key, i, _ = _read_cell(header, i, ", ")
                cols.append(str(key))
                if i < len(header) and header[i] == ",":
                    i += 1
                else:
                    break
            break
        raise ValueError("bad header")
    rows: list[dict[str, Any]] = []
    for line in lines[1:]:
        row = dict(const)
        i = 0
        for ci, col in enumerate(cols):
            value, i, present = _read_cell(line, i, ",")
            if present:
                row[col] = value
            if ci < len(cols) - 1:
                if i >= len(line) or line[i] != ",":
                    raise ValueError("short row")
                i += 1
        if i != len(line):
            raise ValueError("long row")
        rows.append(row)
    return rows


class SmartCrusher:
    """Compress JSON tool output.

    Inspired by Headroom's SmartCrusher. Two stages:

    **Lossless** (always). An array of 3+ objects becomes a table: one header
    naming the columns, then one CSV-like row per object. Columns are the
    union of keys; a column with the same value in every row is hoisted into
    ``const(...)``; a cell is raw text when that cannot be misread and a JSON
    literal otherwise, and an empty cell means the key was absent. Tables nested
    inside an object are rendered the same way and referenced from it. Every
    table is decoded again and compared with the input before it is used.

    **Lossy** (large arrays only). Rows are chosen by an adaptive budget: few
    when the rows are near-duplicates, nearly all when every row is different.
    The first and last rows, error rows, numeric outliers, rows at a change
    point and rows matching the query are always kept. Each gap becomes a marker
    row that carries the CCR id. Long arrays of strings and numbers are sampled
    the same way, with a summary of what was dropped.
    """

    MIN_TABLE_ROWS = 3
    LOSSY_MIN_ROWS = 40
    LOSSY_MIN_CHARS = 4000
    MAX_NESTED_TABLES = 8

    def compress(self, json_str: str, ctx: Context | None = None) -> str:
        ctx = ctx or Context()
        try:
            data = json.loads(json_str)
        except (json.JSONDecodeError, ValueError, RecursionError):
            return json_str
        terms = relevance.tokens(ctx.query)

        if isinstance(data, list) and self._is_table(data):
            return self._table_or_lossy(data, ctx, terms, name="")

        if isinstance(data, dict):
            rendered = self._doc_with_tables(data, ctx, terms)
            if rendered is not None:
                return rendered

        if isinstance(data, list) and len(data) >= self.LOSSY_MIN_ROWS:
            sampled = self._sample_scalars(data, ctx, terms)
            if sampled is not None:
                return sampled

        return dense.elide_blobs(json.dumps(data, separators=(",", ":"), ensure_ascii=False), ctx)

    def compress_lossless(self, json_str: str) -> str:
        """Tables and minification only; never a marker."""
        try:
            data = json.loads(json_str)
        except (json.JSONDecodeError, ValueError, RecursionError):
            return json_str
        if isinstance(data, list) and self._is_table(data):
            table = self._lossless_table(data)
            if table is not None:
                return table
        return json.dumps(data, separators=(",", ":"), ensure_ascii=False)

    # ─── tables ──────────────────────────────────────────────────────────────

    def _is_table(self, lst: list) -> bool:
        if len(lst) < self.MIN_TABLE_ROWS or not all(isinstance(x, dict) and x for x in lst):
            return False
        keys: dict[str, int] = {}
        for d in lst:
            for k in d:
                keys[k] = keys.get(k, 0) + 1
        # Sparse unions (heterogeneous records) render as a wall of commas.
        coverage = sum(keys.values()) / (len(keys) * len(lst))
        return coverage >= 0.5

    def table(self, rows: list[dict[str, Any]], name: str = "", total: int | None = None) -> str:
        """Render rows as a table (no verification, no lossy step)."""
        data = [d for d in rows if "__sensei_marker__" not in d]
        cols: list[str] = list(dict.fromkeys(k for d in data for k in d))
        const: dict[str, Any] = {}
        for k in cols:
            first = data[0].get(k, _MISSING)
            if first is _MISSING or isinstance(first, (dict, list)):
                continue
            if all(k in d and d[k] == first and type(d[k]) is type(first) for d in data):
                const[k] = first
        var = [k for k in cols if k not in const]
        header = "@csv"
        if name:
            header += f" {name}"
        header += f" rows={total if total is not None else len(data)}"
        if const:
            header += (
                " const("
                + ",".join(f"{_key(k)}={_cell(v, header=True)}" for k, v in const.items())
                + ")"
            )
        header += " cols=" + ",".join(_key(k) for k in var)
        lines = [header]
        for d in rows:
            if "__sensei_marker__" in d:
                lines.append(d["__sensei_marker__"])
                continue
            lines.append(",".join(_cell(d.get(k, _MISSING)) for k in var))
        return "\n".join(lines)

    def _lossless_table(self, rows: list[dict[str, Any]], name: str = "") -> str | None:
        if not var_cols_ok(rows):
            return None
        out = self.table(rows, name)
        try:
            ok = decode_table(out if not name else out.replace(f"@csv {name} ", "@csv ", 1)) == rows
        except (ValueError, IndexError, json.JSONDecodeError):
            ok = False
        return out if ok else None

    def _table_or_lossy(
        self, rows: list[dict[str, Any]], ctx: Context, terms: list[str], name: str
    ) -> str:
        lossless = self._lossless_table(rows, name)
        big = lossless is None or len(lossless) > self.LOSSY_MIN_CHARS
        if len(rows) >= self.LOSSY_MIN_ROWS and big:
            keep = self._select_rows(rows, terms)
            if keep is not None:
                return self._render_kept(rows, keep, ctx, name)
        if lossless is not None:
            return lossless
        return json.dumps(rows, separators=(",", ":"), ensure_ascii=False)

    def _render_kept(
        self, rows: list[dict[str, Any]], keep: list[int], ctx: Context, name: str
    ) -> str:
        shown: list[dict[str, Any]] = []
        prev = -1
        for i in keep:
            if i - prev > 1:
                n = i - prev - 1
                shown.append({"__sensei_marker__": ctx.mark(f"{plural(n, 'row')} omitted", n)})
            shown.append(rows[i])
            prev = i
        if prev < len(rows) - 1:
            n = len(rows) - 1 - prev
            shown.append({"__sensei_marker__": ctx.mark(f"{plural(n, 'row')} omitted", n)})
        real = [r for r in shown if "__sensei_marker__" not in r]
        if not var_cols_ok(real):
            return json.dumps(
                [
                    r
                    if "__sensei_marker__" not in r
                    else {"_sensei_omitted": r["__sensei_marker__"]}
                    for r in shown
                ],
                separators=(",", ":"),
                ensure_ascii=False,
            )
        return self.table(shown, name, total=len(rows))

    def _doc_with_tables(self, data: dict, ctx: Context, terms: list[str]) -> str | None:
        """An object whose big arrays of objects are pulled out as tables."""
        tables: list[str] = []
        placeholders: dict[str, str] = {}

        def walk(obj: Any, path: str, depth: int) -> Any:
            if len(tables) >= self.MAX_NESTED_TABLES or depth > 4:
                return obj
            if isinstance(obj, dict):
                return {
                    k: walk(v, f"{path}.{k}" if path else str(k), depth + 1) for k, v in obj.items()
                }
            if isinstance(obj, list) and self._is_table(obj) and _RAW_KEY.match(path or "_"):
                rendered = self._table_or_lossy(obj, ctx, terms, name=path)
                if not rendered.startswith("@csv"):
                    return obj
                tag = f"<@csv {path}>"
                placeholders[tag] = path
                tables.append(rendered)
                return tag
            return obj

        shell = walk(data, "", 0)
        if not tables:
            return None
        head = json.dumps(shell, separators=(",", ":"), ensure_ascii=False)
        # A placeholder that collides with a real string in the payload would
        # make the reference ambiguous.
        if any(head.count(json.dumps(t)) != 1 for t in placeholders):
            return None
        return "\n".join([dense.elide_blobs(head, ctx), *tables])

    # ─── lossy row selection ────────────────────────────────────────────────

    def _select_rows(self, rows: list[dict[str, Any]], terms: list[str]) -> list[int] | None:
        """Indices to keep, or None when the array should not be cut at all."""
        n = len(rows)
        if self._unique_entities(rows):
            # Forty issues, a hundred search hits: each row is a different
            # thing somebody may ask about by name. Sampling them loses facts,
            # however repetitive the field names make them look.
            return None
        texts = [json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows]
        shapes = [_shape(t) for t in texts]
        diversity = len(set(shapes)) / n

        # Adaptive K: coverage of distinct word bigrams as rows are added; the
        # knee is where new rows stop adding new content.
        seen: set[tuple[str, str]] = set()
        curve: list[float] = []
        for t in texts:
            toks = relevance.tokens(t)
            seen.update(pairwise(toks))
            curve.append(len(seen))
        knee = relevance.kneedle(curve)
        k = knee + 1 if knee is not None else math.ceil(n * (0.3 + 0.7 * diversity))
        k = max(12, min(k, n))

        must: set[int] = {0, n - 1}
        for i, t in enumerate(texts):
            if relevance.ERROR_RE.search(t):
                must.add(i)
        for col in dict.fromkeys(c for r in rows for c in r):
            nums = [
                (i, float(r[col]))
                for i, r in enumerate(rows)
                if isinstance(r.get(col), (int, float)) and not isinstance(r.get(col), bool)
            ]
            if len(nums) >= n * 0.8:
                vals = [v for _, v in nums]
                must.update(nums[j][0] for j in relevance.zscore_outliers(vals))
                for cp in relevance.change_points(vals):
                    must.update({nums[cp - 1][0], nums[cp][0]})
            # A categorical value that occurs once or twice in a big array is
            # the row somebody will ask about (the one failed status).
            cats = [r.get(col) for r in rows if isinstance(r.get(col), str)]
            if len(cats) >= n * 0.8:
                freq: dict[str, int] = {}
                for c in cats:
                    freq[c] = freq.get(c, 0) + 1
                if len(freq) <= max(3, n // 10):
                    must.update(i for i, r in enumerate(rows) if freq.get(r.get(col), 99) <= 2)
        if terms:
            scores = relevance.bm25([relevance.tokens(t) for t in texts], terms)
            cut = relevance.otsu_threshold(scores)
            must.update(i for i, s in enumerate(scores) if s > 0 and s >= cut)

        if k >= n * 0.8 and len(must) < n:
            # Diverse rows: nothing to gain that is worth a cut.
            return None
        head = max(1, int(k * 0.3))
        tail = max(1, int(k * 0.15))
        keep = set(range(head)) | set(range(n - tail, n)) | must
        # Fill the remaining budget with rows that add the most new shapes.
        budget = k - len(keep)
        if budget > 0:
            covered = {shapes[i] for i in keep}
            for i in range(n):
                if budget <= 0:
                    break
                if i not in keep and shapes[i] not in covered:
                    keep.add(i)
                    covered.add(shapes[i])
                    budget -= 1
            # Whatever is left extends the head: one more contiguous run reads
            # better and costs fewer gap markers than an even spread.
            for i in range(n):
                if budget <= 0:
                    break
                if i not in keep:
                    keep.add(i)
                    budget -= 1
        if len(keep) >= n * 0.85:
            return None
        return sorted(keep)

    # Above this many rows a retrievable cut beats sending every record.
    UNIQUE_ENTITY_MAX_ROWS = 300

    def _unique_entities(self, rows: list[dict[str, Any]]) -> bool:
        """Records (issues, users, search hits), not a stream of events.

        Sampling is for streams: log lines, metrics, polling results, where
        rows repeat a template and the interesting ones stand out. A list of
        records is different — every row is a thing somebody may ask about by
        name — so it is only ever tabulated, never cut, unless it is huge.

        A stream is ordered by time: some column holds timestamps that only go
        one way. Even then, a column of free text whose rows differ in words
        (commit messages, issue titles) makes it a list of records. Without a
        time order, only rows that are near copies of each other count as a
        stream.
        """
        n = len(rows)
        if n > self.UNIQUE_ENTITY_MAX_ROWS:
            return False
        columns: dict[str, list[str]] = {}
        for r in rows:
            for k, v in r.items():
                if isinstance(v, str):
                    columns.setdefault(k, []).append(v)
        dense = {k: v for k, v in columns.items() if len(v) >= n * 0.8}
        ordered = False
        for v in dense.values():
            stamps = [x for x in v if _TIMESTAMP.match(x)]
            if len(stamps) < len(v) * 0.9:
                continue
            up = sum(1 for x, y in pairwise(stamps) if y >= x)
            if up >= (len(stamps) - 1) * 0.9 or up <= (len(stamps) - 1) * 0.1:
                ordered = True
        if not ordered:
            # A unique, human-readable key (SHOP-1231, a username, a path) is
            # what people ask about; a uuid or a hash is not.
            for v in dense.values():
                if (
                    len(set(v)) == len(v)
                    and sum(1 for x in v if _LETTER.search(x) and not _HEXISH.fullmatch(x))
                    >= len(v) * 0.9
                ):
                    return True
            shapes = {_shape(json.dumps(r, sort_keys=True, ensure_ascii=False)) for r in rows}
            return len(shapes) >= n * 0.1
        for v in dense.values():
            if sum(1 for x in v if _TIMESTAMP.match(x)) >= len(v) * 0.5:
                continue
            words = [x for x in v if " " in x.strip()]
            if len(words) >= len(v) * 0.5 and len({_shape(x) for x in v}) >= len(v) * 0.7:
                return True
        return False

    def _sample_scalars(self, data: list, ctx: Context, terms: list[str]) -> str | None:
        n = len(data)
        if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in data):
            vals = [float(x) for x in data]
            keep = set(range(10)) | set(range(n - 5, n))
            keep |= relevance.zscore_outliers(vals)
            for cp in relevance.change_points(vals):
                keep |= {cp - 1, cp}
            if len(keep) >= n * 0.7:
                return None
            q = statistics.quantiles(vals, n=4) if n >= 4 else [vals[0]] * 3
            summary = (
                f"min {_num(min(vals))}, p25 {_num(q[0])}, median {_num(q[1])}, "
                f"p75 {_num(q[2])}, max {_num(max(vals))}, mean {_num(statistics.fmean(vals))}"
            )
            return self._render_scalar_sample(data, sorted(keep), ctx, "number", summary)
        if all(isinstance(x, str) for x in data):
            distinct = len(set(data))
            keep = set(range(15)) | set(range(n - 5, n))
            keep |= {i for i, s in enumerate(data) if relevance.ERROR_RE.search(s)}
            lengths = [float(len(s)) for s in data]
            keep |= relevance.zscore_outliers(lengths)
            if terms:
                scores = relevance.bm25([relevance.tokens(s) for s in data], terms)
                cut = relevance.otsu_threshold(scores)
                keep |= {i for i, s in enumerate(scores) if s > 0 and s >= cut}
            first_seen: dict[str, int] = {}
            for i, s in enumerate(data):
                first_seen.setdefault(s, i)
            if distinct <= 40:
                keep |= set(first_seen.values())
            if len(keep) >= n * 0.7:
                return None
            summary = f"{distinct:,} distinct values in all {n:,}"
            return self._render_scalar_sample(data, sorted(keep), ctx, "string", summary)
        return None

    @staticmethod
    def _render_scalar_sample(
        data: list, keep: list[int], ctx: Context, kind: str, summary: str
    ) -> str:
        out: list[Any] = []
        prev = -1
        for i in keep:
            if i - prev > 1:
                n = i - prev - 1
                out.append(ctx.mark(f"{plural(n, kind)} omitted", n))
            out.append(data[i])
            prev = i
        if prev < len(data) - 1:
            n = len(data) - 1 - prev
            out.append(ctx.mark(f"{plural(n, kind)} omitted", n))
        out.append(ctx.mark(f"{kind} array of {len(data):,}: {summary}", 0))
        return json.dumps(out, separators=(",", ":"), ensure_ascii=False)


class _Missing:
    pass


_MISSING = _Missing()

_SHAPE_NUM = re.compile(r"\d+(?:\.\d+)?")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2})?")
_LETTER = re.compile(r"[A-Za-z]")
_HEXISH = re.compile(r"[0-9a-fA-F-]{8,}")
_SHAPE_HEX = re.compile(r"\b[0-9a-f]{8,}\b|\b[0-9a-f-]{36}\b")


def _shape(text: str) -> str:
    return _SHAPE_NUM.sub("#", _SHAPE_HEX.sub("@", text))


def _num(v: float) -> str:
    return f"{v:.4g}"


def var_cols_ok(rows: list[dict[str, Any]]) -> bool:
    """A table needs at least one column and rows that are all objects."""
    return bool(rows) and all(isinstance(r, dict) for r in rows) and any(rows)
