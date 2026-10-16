"""The measurement system behind every number in the README.

A benchmark that is wrong is worse than none: it is believed. These tests pin
the properties the published numbers rely on — the corpus is reproducible,
every declared fact is really in its sample, the cost model does the arithmetic
it documents, the session replay never lets transcript text out, and the README
says exactly what the committed results say.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks import agent_bench, cost, readme, refresh, session_replay
from benchmarks.corpus import DEFAULT_SEED, KINDS, build_corpus, corpus_digest
from benchmarks.harness import SenseiCompressor, Tokenizer, missing_facts, percentile

CORPUS = build_corpus()


# ─── Corpus ──────────────────────────────────────────────────────────────────


def test_corpus_is_reproducible() -> None:
    assert corpus_digest(build_corpus(DEFAULT_SEED)) == corpus_digest(CORPUS)
    assert corpus_digest(build_corpus(DEFAULT_SEED + 1)) != corpus_digest(CORPUS)


def test_committed_results_match_the_corpus() -> None:
    """A results file from another corpus would publish numbers nobody can reproduce."""
    data = json.loads((agent_bench.DEFAULT_OUT).read_text(encoding="utf-8"))
    assert data["corpus"]["seed"] == DEFAULT_SEED
    assert data["corpus"]["digest"] == corpus_digest(CORPUS)


@pytest.mark.parametrize("sample", CORPUS, ids=lambda s: s.name)
def test_every_sample_declares_facts_that_exist(sample) -> None:
    assert sample.facts, f"{sample.name} checks nothing"
    for fact in sample.facts:
        assert fact in sample.text, f"{sample.name}: {fact!r} is not in the input"
    if sample.answer:
        assert sample.answer in sample.facts


def test_kinds_and_names() -> None:
    names = [s.name for s in CORPUS]
    assert len(names) == len(set(names))
    assert {s.kind for s in CORPUS if s.group == "agent"} == set(KINDS)
    groups = {s.group for s in CORPUS}
    assert {"headroom:code_search", "headroom:sre_incident"} <= groups


def test_file_reads_are_the_byte_exact_ones() -> None:
    exact = {s.kind for s in CORPUS if s.byte_exact}
    assert exact == {"file_read", "cat_source"}


def test_sensei_keeps_file_reads_byte_exact() -> None:
    sensei = SenseiCompressor()
    for s in CORPUS:
        if s.byte_exact:
            assert sensei.compress(s.text) == s.text, s.name


# ─── Harness ─────────────────────────────────────────────────────────────────


def test_percentile_and_facts() -> None:
    assert percentile([], 50) == 0.0
    assert percentile([1, 2, 3, 4], 50) == 2
    assert percentile(list(range(1, 101)), 95) == 95
    assert missing_facts(["a  b", "zz"], "x a b y") == ["zz"]


# ─── Cost model ──────────────────────────────────────────────────────────────


def test_bill_arithmetic() -> None:
    price = cost.Pricing("t", 1_000_000.0, 2_000_000.0, cache_write=1.25, cache_read=0.1)
    turns = [cost.Turn(10, 1), cost.Turn(20, 2)]
    b = cost.bill(turns, price, prefix=100)
    # Request 1 writes prefix+10; request 2 reads 110 and writes the answer (1) + 20.
    assert b.cache_write == pytest.approx((110 + 21) * 1.25)
    assert b.cache_read == pytest.approx(110 * 0.1)
    assert b.output == pytest.approx(3 * 2)
    u = cost.bill(turns, price, prefix=100, cached=False)
    assert u.uncached == pytest.approx(110 + 131)


def test_saved_token_is_worth_write_plus_reads() -> None:
    price = cost.PRICES["generic"]
    assert cost.tool_result_savings(1000, 9, price) == pytest.approx(
        1000 * price.per_token() * (1.25 + 0.1 * 9)
    )


def test_caching_shrinks_the_dollar_saving() -> None:
    """The point of the model: token % overstates bill % in a cached session."""
    before, after = [5000] * 20, [2500] * 20
    out = cost.compare(before, after)
    tokens_pct = 50.0
    assert 0 < out["cached"]["saved_pct"] < out["uncached"]["saved_pct"] < tokens_pct


# ─── Session replay ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("command", "family"),
    [
        ("git log --oneline -5", "git"),
        ("cd backend && pytest -q", "test"),
        ("FOO=1 rg -n handler src/", "search"),
        ("ls -la", "listing"),
        ("cat README.md | head", "file_view"),
        ("npm install", "install"),
        ("cargo build --release", "build"),
        ("./my-secret-script --flag", "run"),
        ("frobnicate --all", "other"),
    ],
)
def test_shell_family(command: str, family: str) -> None:
    assert session_replay.shell_family(command) == family


def _fake_claude_session(path: Path, marker: str) -> None:
    lines = [
        {
            "type": "assistant",
            "message": {
                "id": "m1",
                "usage": {
                    "input_tokens": 3,
                    "cache_creation_input_tokens": 1000,
                    "cache_read_input_tokens": 0,
                    "output_tokens": 50,
                },
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Bash",
                        "input": {"command": f"grep -rn {marker} src/"},
                    }
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": "\n".join(
                            f"src/{marker}_{i}.py:{i}:    x = 1" for i in range(40)
                        ),
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "message": {
                "id": "m2",
                "usage": {
                    "input_tokens": 3,
                    "cache_creation_input_tokens": 400,
                    "cache_read_input_tokens": 1000,
                    "output_tokens": 80,
                },
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t2",
                        "name": "mcp__private_server__lookup",
                        "input": {},
                    }
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t2",
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    [{"id": i, "owner": marker, "ok": True} for i in range(30)]
                                ),
                            }
                        ],
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "message": {
                "id": "m3",
                "usage": {
                    "input_tokens": 3,
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 1400,
                    "output_tokens": 20,
                },
                "content": [],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")


def test_replay_summary_contains_numbers_only(tmp_path: Path) -> None:
    # A recognisable marker, not a credential: it must never reach the summary.
    marker = "_".join(("zebracorn", "transcript", "marker"))
    proj = tmp_path / "claude" / "C--Users-someone-secret-project"
    proj.mkdir(parents=True)
    _fake_claude_session(proj / "s.jsonl", marker)
    files = list(session_replay.discover(tmp_path / "claude", None))
    summary = session_replay.replay(
        files, {"sensei": SenseiCompressor()}, Tokenizer(), cost.PRICES["generic"], progress=False
    )
    dumped = json.dumps(summary)
    assert marker not in dumped
    assert "secret-project" not in dumped and "private_server" not in dumped
    assert set(summary["by_category"]) == {"shell:search", "mcp"}
    assert summary["requests"] == 3
    assert summary["total"]["results"] == 2
    assert summary["bill_usd"]["total"] > 0
    # What is written to disk carries no absolute spend, only shares.
    shared = session_replay.shareable(summary)
    assert "usd" not in json.dumps(shared)
    assert sum(shared["bill_mix_pct"].values()) == pytest.approx(100, abs=0.1)
    assert "bill_saved_pct" in shared["by_category"]["mcp"]["sensei"]


# ─── Gate and README ─────────────────────────────────────────────────────────


def _committed() -> dict:
    return json.loads(agent_bench.DEFAULT_OUT.read_text(encoding="utf-8"))


def test_check_flags_drops_and_lost_facts() -> None:
    base = _committed()
    assert agent_bench.check(base, base, 1.0) == []
    worse = json.loads(json.dumps(base))
    worse["summary"]["sensei"]["agent"]["saved_pct"] -= 5
    worse["samples"][0]["sensei"]["missing"] = [*worse["samples"][0]["sensei"]["missing"], "x"]
    problems = agent_bench.check(worse, base, 1.0)
    assert any("savings fell" in p for p in problems)
    assert any("lost" in p for p in problems)


def test_readme_block_replacement() -> None:
    text = f"intro\n{readme.START}\nold\n{readme.END}\noutro"
    out = readme.update(text, f"{readme.START}\nnew\n{readme.END}")
    assert out == f"intro\n{readme.START}\nnew\n{readme.END}\noutro"
    with pytest.raises(ValueError):
        readme.update("no markers", "x")


def test_readme_and_graphics_match_committed_results() -> None:
    """What `refresh --check` enforces nightly, so a PR sees it immediately."""
    assert refresh.stale() == [], "run `python -m benchmarks.refresh --render-only`"
