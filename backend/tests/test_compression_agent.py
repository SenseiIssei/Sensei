"""The agent-traffic compressors: search, diff, git, listings, test output,
tables, dense lines, HTML, config, extractive prose, folds and markers.

Every lossy compressor is checked for the same three things: the line that
matters survives, the cut is marked with a retrievable CCR id, and the result
is never larger than the input.
"""

from __future__ import annotations

import json
import random
import re
import time

import pytest

from sensei.compression import folds
from sensei.compression.cachealign import CacheAligner
from sensei.compression.ccr import CCRStore
from sensei.compression.configcomp import ConfigCompressor
from sensei.compression.dense import elide_blobs, elide_dense
from sensei.compression.diffcomp import DiffCompressor
from sensei.compression.gitcomp import GitCompressor, fold_crlf_warnings
from sensei.compression.htmlcomp import HTMLCompressor
from sensei.compression.listing import ListingCompressor
from sensei.compression.logcomp import LogCompressor
from sensei.compression.markers import MARKER_RE, Context, ccr_id_for
from sensei.compression.router import ContentRouter, ContentType, _is_prose
from sensei.compression.search import SearchCompressor
from sensei.compression.search import detect as detect_search
from sensei.compression.smartcrusher import SmartCrusher, decode_table
from sensei.compression.textcomp import TextCompressor
from sensei.compression.textcrusher import TextCrusher
from sensei.config import settings

ID = "0123456789abcdef"


def ctx(query: str = "") -> Context:
    return Context(ccr_id=ID, query=query)


def markers(text: str) -> list[re.Match[str]]:
    return list(MARKER_RE.finditer(text))


# ─── markers ────────────────────────────────────────────────────────────────


class TestMarkers:
    def test_format_matches_the_published_contract(self):
        c = ctx()
        m = c.mark("37 lines omitted", 37)
        assert m == f"[sensei: 37 lines omitted; retrieve ccr={ID}]"
        found = markers(m)
        assert found and found[0].group(1) == "37 lines omitted" and found[0].group(2) == ID
        assert c.lossy and c.omitted == 37

    def test_description_cannot_break_the_marker(self):
        m = ctx().mark("a [weird]; path\nname")
        assert len(markers(m)) == 1
        assert "\n" not in m

    def test_without_a_store_there_is_no_retrieve_clause(self):
        m = Context().mark("3 rows omitted")
        assert m == "[sensei: 3 rows omitted]"

    def test_id_is_deterministic(self):
        assert ccr_id_for("abc") == ccr_id_for("abc") != ccr_id_for("abd")
        assert re.fullmatch(r"[0-9a-f]{16}", ccr_id_for("abc"))


# ─── lossless folds ─────────────────────────────────────────────────────────


class TestFolds:
    def test_random_inputs_round_trip(self):
        rng = random.Random(7)
        alphabet = ["a", "b", "", "x" * 50, "(previous line repeated 2 more times)", "--"]
        for _ in range(2000):
            text = "\n".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
            out = folds.fold(text)
            assert out == text or folds.unfold(out) == text

    def test_runs_and_blocks(self):
        block = [
            "retrying connection to db-01",
            "backing off for 250 ms",
            "attempt failed: refused",
        ]
        text = "\n".join(["Compiling the same crate again and again"] * 30 + block * 6)
        out = folds.fold(text)
        assert "(previous line repeated 29 more times)" in out
        assert "(previous 3 lines repeated 5 more times)" in out
        assert folds.unfold(out) == text

    def test_earlier_block_back_reference(self):
        trace = [f'  File "/app/mod{i}.py", line {i * 10}, in handler_{i}' for i in range(6)]
        text = "\n".join(["first failure", *trace, "something else", "second failure", *trace])
        out = folds.fold(text)
        assert "lines identical to the" in out
        assert folds.unfold(out) == text

    def test_terminal_rendering(self):
        raw = "\x1b[32m✓\x1b[0m built\n 10%\r 50%\r100%\ndone\r\n"
        assert folds.render_terminal(raw) == "✓ built\n100%\ndone\n"

    def test_large_input_is_fast(self):
        text = "\n".join(f"{i % 7} " + "y" * 40 for i in range(20000))
        t0 = time.perf_counter()
        folds.fold(text)
        assert time.perf_counter() - t0 < 2.0


# ─── search ─────────────────────────────────────────────────────────────────


def _grep(files: int, hits: int) -> str:
    return "\n".join(
        f"src/pkg/module_{f}.py:{10 + k}:    value = compute(item_{k})"
        for f in range(files)
        for k in range(hits)
    )


class TestSearch:
    def test_grouping_is_lossless(self):
        text = _grep(4, 5)
        out = SearchCompressor().group(text)
        assert out.count("src/pkg/module_2.py") == 1
        assert SearchCompressor.ungroup(out) == text
        assert len(out) < len(text)

    def test_windows_paths_and_context_lines(self):
        text = "\n".join(
            [
                r"C:\work\app\main.rs:12:fn main() {",
                r"C:\work\app\main.rs-13-    let x = 1;",
                "--",
                r"C:\work\app\main.rs:40:    run(x);",
                r"C:\work\app\lib.rs:3:pub mod x;",
            ]
        )
        assert detect_search(text)
        out = SearchCompressor().group(text)
        assert SearchCompressor.ungroup(out) == text
        assert out.count(r"C:\work\app\main.rs") == 1

    def test_timestamped_log_is_not_a_search_result(self):
        log = "\n".join(f"2026-06-26 14:00:{i:02d} INFO step {i}" for i in range(20))
        assert not detect_search(log)

    def test_caps_keep_errors_and_mark_the_rest(self):
        lines = _grep(40, 8).split("\n")
        lines[170] = "src/pkg/module_21.py:12:    raise CacheError('poisoned')"
        text = "\n".join(lines)
        c = ctx()
        out = SearchCompressor().compress(text, c)
        assert "raise CacheError('poisoned')" in out
        assert c.lossy and markers(out)
        assert all(m.group(2) == ID for m in markers(out))
        assert len(out) < len(text) / 2

    def test_small_results_are_never_cut(self):
        c = ctx()
        SearchCompressor().compress(_grep(3, 4), c)
        assert not c.lossy

    def test_long_line_keeps_the_query_window(self):
        line = "bundle.js:1:" + "a=1;" * 3000 + "refreshSession(token)" + "b=2;" * 3000
        c = ctx("refreshSession")
        out = SearchCompressor().compress(line + "\n" + line.replace(":1:", ":2:"), c)
        assert "refreshSession(token)" in out
        assert len(out) < len(line) / 5


# ─── diff ───────────────────────────────────────────────────────────────────


def _diff() -> str:
    lines = [
        "diff --git a/src/r.rs b/src/r.rs",
        "--- a/src/r.rs",
        "+++ b/src/r.rs",
        "@@ -1,40 +1,40 @@",
    ]
    lines += [f"     let a{i} = {i};" for i in range(20)]
    lines += ["-    old_call();", "+    new_call();"]
    lines += [f"     let b{i} = {i};" for i in range(20)]
    lines += ["diff --git a/package-lock.json b/package-lock.json", "--- a/package-lock.json",
              "+++ b/package-lock.json", "@@ -1,30 +1,30 @@"]  # fmt: skip
    lines += [f'-  "v{i}": "1.0.0",' for i in range(30)] + [
        f'+  "v{i}": "1.0.1",' for i in range(30)
    ]
    return "\n".join(lines)


class TestDiff:
    def test_changes_kept_context_and_lockfile_cut(self):
        text = _diff()
        c = ctx()
        out = DiffCompressor().compress(text, c)
        assert "-    old_call();" in out and "+    new_call();" in out
        assert "package-lock.json" in out and '"v17"' not in out
        assert "     let a10 = 10;" not in out
        assert c.lossy and markers(out)

    def test_short_diff_untouched(self):
        text = "\n".join(_diff().split("\n")[:30])
        assert DiffCompressor().compress(text, ctx()) == text


# ─── git ────────────────────────────────────────────────────────────────────


class TestGit:
    def test_status_hints_go_files_stay(self):
        text = "\n".join(
            [
                "On branch main",
                "Changes not staged for commit:",
                '  (use "git add <file>..." to update what will be committed)',
                "\tmodified:   src/a.rs",
            ]
        )
        out = GitCompressor().compress(text)
        assert 'use "git add' not in out and "src/a.rs" in out and "On branch main" in out

    def test_log_header_becomes_one_line(self):
        text = "\n".join(
            f"commit {i:040x}\nAuthor: A <a@x>\nDate:   Thu Oct {i + 1} 2026\n\n    msg {i}\n"
            for i in range(5)
        )
        out = GitCompressor().compress(text)
        assert "(all commits below by A <a@x>)" in out
        assert f"{3:040x} | Thu Oct 4 2026" in out and "    msg 3" in out

    def test_crlf_warnings_folded_with_every_file(self):
        names = [f"src/f{i}.rs" for i in range(5)]
        text = "\n".join(
            f"warning: in the working copy of '{n}', LF will be replaced by CRLF the next time "
            "Git touches it"
            for n in names
        )
        out = fold_crlf_warnings(text)
        assert out.count("warning:") == 1 and all(n in out for n in names)


# ─── listings ───────────────────────────────────────────────────────────────


class TestListing:
    def test_paths_grouped_losslessly(self):
        files = [f"src/{d}/file_{i}.ts" for d in ("a", "b") for i in range(10)]
        text = "\n".join(files)
        out = ListingCompressor().compress(text, ctx())
        assert out.count("src/a/") == 1
        assert ListingCompressor._ungroup(out.split("\n")) == files

    def test_ls_long_hoists_owner_and_group(self):
        rows = [f"-rw-r--r-- 1 jakob 197609 {100 + i} Oct 14 14:45 file_{i}.json" for i in range(8)]
        out = ListingCompressor().compress("total 80\n" + "\n".join(rows), ctx())
        assert "(owner=jakob group=197609 links=1 for all below)" in out
        assert "-rw-r--r-- 104 Oct 14 14:45 file_4.json" in out


# ─── logs, tests, builds ────────────────────────────────────────────────────


class TestLogs:
    def test_failing_test_survives_passing_ones_marked(self):
        lines = [f"test suite::case_{i} ... {'FAILED' if i == 77 else 'ok'}" for i in range(200)]
        lines += ["", "test result: FAILED. 199 passed; 1 failed; 0 ignored"]
        c = ctx()
        out = LogCompressor().compress("\n".join(lines), c)
        assert "test suite::case_77 ... FAILED" in out
        assert "199 passed; 1 failed" in out
        assert "progress lines omitted" in out and c.lossy

    def test_repeated_diagnostics_keep_their_locations(self):
        block = (
            "warning: unused variable: `x{i}`\n"
            "  --> src/m{i}.rs:{i}:9\n"
            "   |\n"
            "{i} |     let x{i} = 1;\n"
            "   |         ^^ help: prefix it with an underscore\n"
        )
        text = "\n".join(block.format(i=i) for i in range(10)) + "\nwarning: 10 warnings emitted"
        c = ctx()
        out = LogCompressor().compress(text, c)
        assert "src/m0.rs:0:9" in out and "src/m9.rs:9:9" in out
        assert out.count("warning: unused variable") <= 3
        assert c.lossy

    def test_router_never_grows_a_log(self):
        router = ContentRouter(enable_caching=False)
        text = "\n".join(f"ERROR e{i}" for i in range(12))
        assert len(router.compress(text).compressed) <= len(text)


# ─── JSON ───────────────────────────────────────────────────────────────────


_TRICKY = ["", " lead", "trail ", "a,b", 'q"q', "true", "null", "12", "1e5", "[x", "{y", "x=y",
           "(p)", "line\nbreak", "naïve", "NaN", "-0"]  # fmt: skip


class TestSmartCrusher:
    def test_table_round_trip_on_random_records(self):
        rng = random.Random(3)
        sc = SmartCrusher()
        for _ in range(300):
            keys = ["id", "name", "type", "url", "v", "nested"]
            rows = []
            for i in range(rng.randint(3, 12)):
                row = {}
                for k in keys:
                    if rng.random() < 0.8:
                        row[k] = rng.choice(
                            [i, rng.random(), rng.choice(_TRICKY), True, False, {"type": "t"}, [1]]
                        )
                rows.append(row)
            if not any(rows) or not all(rows):
                continue
            data = json.loads(json.dumps(rows))
            out = sc.compress(json.dumps(data))
            if out.startswith("@csv"):
                expect = [{k: v for k, v in r.items() if v not in ("", None, [], {})} for r in data]
                assert decode_table(out) == expect, out

    def test_large_array_keeps_error_and_outlier_rows(self):
        rows = [
            {"id": i, "status": "ok", "route": f"/v1/items/{i % 4}", "ms": 20 + i % 3}
            for i in range(300)
        ]
        rows[211] = {"id": 211, "status": "error", "route": "/v1/items/3", "ms": 9000,
                     "error": "db timeout"}  # fmt: skip
        c = ctx()
        out = SmartCrusher().compress(json.dumps(rows), c)
        assert "db timeout" in out and "211" in out
        assert c.lossy and "rows omitted" in out
        assert out.startswith("@csv rows=300 ")
        assert len(out) < len(json.dumps(rows)) / 4

    def test_unique_records_are_not_sampled(self):
        rows = [
            {"id": i, "title": f"issue about {w}", "author": f"user{i}"}
            for i, w in enumerate(f"word{n}" for n in range(60))
        ]
        c = ctx()
        SmartCrusher().compress(json.dumps(rows), c)
        assert not c.lossy

    def test_number_and_string_arrays(self):
        c = ctx()
        out = json.loads(SmartCrusher().compress(json.dumps([*range(400), 99999]), c))
        assert 99999 in out and any("numbers omitted" in str(x) for x in out)
        c2 = ctx()
        strings = [f"ok {i % 3}" for i in range(300)] + ["fatal: disk full"]
        out2 = json.loads(SmartCrusher().compress(json.dumps(strings), c2))
        assert "fatal: disk full" in out2 and c2.lossy

    def test_lossless_only_entry_point(self):
        rows = [{"id": i, "v": "x"} for i in range(200)]
        out = SmartCrusher().compress_lossless(json.dumps(rows))
        assert not markers(out) and len(decode_table(out)) == 200

    def test_base64_value_is_elided_with_a_marker(self):
        blob = "iVBORw0KGgoAAAANSUhEUgAA" + "QUJDRGVmZ2hpams0NTY3" * 40
        c = ctx()
        out = SmartCrusher().compress(json.dumps({"name": "shot.png", "data": blob}), c)
        assert "shot.png" in out and "base64 blob" in out and c.lossy


# ─── dense lines, HTML, config, prose ───────────────────────────────────────


class TestDense:
    def test_blob_and_dense_line(self):
        blob = "data:image/png;base64," + "QUJDRGVmZ2hpams0NTY3" * 50
        c = ctx()
        assert "base64 blob of" in elide_blobs(f"<img src='{blob}'>", c)
        line = "x=1;" * 500 + "needle()" + "y=2;" * 500
        c2 = ctx("needle")
        out = elide_dense(line, c2)
        assert "needle()" in out and len(out) < len(line) / 3 and c2.lossy

    def test_hex_hash_is_not_base64(self):
        h = "0123456789abcdef" * 20
        assert elide_blobs(h, ctx()) == h


class TestHtml:
    def test_main_content_kept_chrome_dropped(self):
        page = (
            "<!DOCTYPE html><html><head><title>Docs</title><script>var a=1;</script></head>"
            "<body><nav><a href='/x'>Menu item</a></nav><main><h1>Install</h1>"
            "<p>Run <code>pip install sensei-gateway</code> first.</p></main>"
            "<footer>(c) 2026</footer></body></html>"
        ) + "<!-- pad -->" * 50
        c = ctx()
        out = HTMLCompressor().compress(page, c)
        assert "# Install" in out and "`pip install sensei-gateway`" in out
        assert "Menu item" not in out and "var a" not in out and c.lossy


class TestConfig:
    def test_comments_marked_values_kept(self):
        text = (
            "# top comment\nserver:\n  # inner\n  port: 8080\n  host: 0.0.0.0\nlog: debug\nx: 1\n"
        )
        c = ctx()
        out = ConfigCompressor().compress(text, c)
        assert "port: 8080" in out and "# inner" not in out and "2 comment lines" in out

    def test_config_tool_result_is_protected(self):
        text = "[server]\nport = 8080\nhost = '0.0.0.0'\n[log]\nlevel = 'debug'\nfile = 'x.log'\n"
        router = ContentRouter(enable_caching=False)
        res = router.compress(text, edit_target=True)
        assert res.content_type is ContentType.config and res.compressed == text


class TestTextCrusher:
    def test_keeps_relevant_and_salient_sentences(self):
        filler = "The weather in the valley was pleasant and the walk was long. "
        doc = (
            filler * 6
            + "The retry budget must not exceed 4 attempts per request. "
            + filler * 6
            + "Configure it in config/retry.toml under max_attempts. "
            + filler * 6
        )
        c = ctx("how many retry attempts are allowed")
        out = TextCrusher(ratio=0.3, min_chars=200).compress(doc, c)
        assert "must not exceed 4 attempts" in out
        assert "config/retry.toml" in out
        assert c.lossy and "sentence" in out and len(out) < len(doc)


# ─── router ─────────────────────────────────────────────────────────────────


class TestRouter:
    def test_never_grows_random_payloads(self):
        rng = random.Random(11)
        router = ContentRouter(enable_caching=False)
        pieces = [
            "ERROR x",
            "a:1:b",
            "src/x.py:3:y",
            "{",
            "}",
            "test a ... ok",
            "- item",
            "  ",
            "é",
        ]
        for _ in range(300):
            text = "\n".join(rng.choice(pieces) for _ in range(rng.randint(0, 40)))
            res = router.compress(text, edit_target=rng.random() < 0.5)
            assert len(res.compressed) <= len(text)

    def test_marker_id_retrieves_the_original(self, tmp_path):
        store = CCRStore(cache_dir=tmp_path)
        router = ContentRouter(ccr_store=store, enable_caching=True)
        text = (
            "\n".join(f"test m::t{i} ... ok" for i in range(300)) + "\ntest result: ok. 300 passed"
        )
        res = router.compress(text, edit_target=True)
        found = markers(res.compressed)
        assert found and res.metadata["lossy"]
        assert found[0].group(2) == res.ccr_id == ccr_id_for(text)
        assert router.retrieve_original(found[0].group(2)) == text

    def test_same_input_same_bytes(self, tmp_path):
        router = ContentRouter(ccr_store=CCRStore(cache_dir=tmp_path), enable_caching=True)
        text = _grep(40, 8)
        assert router.compress(text).compressed == router.compress(text).compressed

    def test_code_in_a_mixed_output_stays_byte_exact(self):
        code = "def f(x):\n    # keep this comment\n    return x  # and this\n"
        text = (
            "On branch main\nnothing to commit, working tree clean\n\n"
            + _grep(3, 3)
            + "\n\n"
            + code
        )
        res = ContentRouter(enable_caching=False).compress(text, edit_target=True)
        assert code.rstrip("\n") in res.compressed

    def test_identifiers_are_not_capitalised(self):
        text = "\n".join(f"tests::scheduler::case_{i}  basically fine" for i in range(10))
        res = ContentRouter(enable_caching=False).compress(text, force_type=ContentType.text)
        assert "tests::scheduler::case_3" in res.compressed

    def test_prose_detector(self):
        assert _is_prose("This is a sentence with several plain words in it. " * 5)
        assert not _is_prose("tests::a::b ... ok\nsrc/x.rs:12:9\n{ a = 1; }")

    def test_lossy_off_means_no_markers(self, monkeypatch):
        monkeypatch.setattr(settings, "compression_lossy", False)
        text = "\n".join(f"test m::t{i} ... ok" for i in range(300))
        res = ContentRouter(enable_caching=False).compress(text, edit_target=True)
        assert not markers(res.compressed) and not res.metadata["lossy"]

    @pytest.mark.parametrize(
        "payload",
        [
            'fn main() {\n    let x = 1;\n    println!("{x}");\n}\n',
            '{\n  "name": "pkg",\n  "version": "1.0.0",\n  "scripts": {"test": "pytest"}\n}\n',
            "     1\u2192import os\n     2\u2192\n     3\u2192print(os.name)\n",
        ],
    )
    def test_edit_targets_pass_through_byte_exact(self, payload):
        res = ContentRouter(enable_caching=False).compress(payload, edit_target=True)
        assert res.compressed == payload

    def test_one_line_json_object_is_an_api_response_not_a_file(self):
        rows = [{"id": i, "name": f"item {i}", "state": "open"} for i in range(30)]
        payload = json.dumps({"total": 30, "items": rows})
        res = ContentRouter(enable_caching=False).compress(payload, edit_target=True)
        assert res.compressed.startswith('{"total":30,"items":"<@csv items>"}')
        assert len(res.compressed) < len(payload) / 2


class TestCacheAligner:
    def test_same_lengths_different_content_do_not_collide(self):
        al = CacheAligner()
        a = al.align([{"role": "system", "content": "aaaa"}, {"role": "user", "content": "1111"}])
        b = al.align([{"role": "system", "content": "bbbb"}, {"role": "user", "content": "2222"}])
        assert a[0]["content"] == "aaaa" and b[0]["content"] == "bbbb"
        assert b[1]["content"] == "2222"

    def test_cached_result_cannot_be_mutated_by_a_caller(self):
        al = CacheAligner()
        msgs = [{"role": "user", "content": "hello"}]
        first = al.align(msgs)
        first[0]["content"] = "changed"
        assert al.align(msgs)[0]["content"] == "hello"


class TestTextCompressorRegex:
    def test_aligned_columns_are_linear(self):
        line = "LISTEN 0 511 127.0.0.1:7100" + " " * 3000 + "users:((node))"
        t0 = time.perf_counter()
        TextCompressor().compress("\n".join([line] * 5))
        assert time.perf_counter() - t0 < 1.0
