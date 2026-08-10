"""Does compression still contain the facts the model needs?

`compression_benchmark.py` proves text gets smaller. That is a different claim
from "the model still answers correctly", and only the first one has been
checked anywhere in this repository until now. A user's actual question is not
"how many tokens did you remove" but "did you remove something I needed", and
the README's 79% says nothing about that.

This measures the honest, checkable half of it.

## What this proves, and what it does not

Each corpus entry is a realistic agent payload paired with the **facts** an
agent would have to extract from it: the error message in a build log, the
failing frame in a stack trace, specific ids and values in a JSON response, a
function signature in source. After compression, every fact must still be
literally present.

That is a **necessary condition**, not a sufficient one:

- If a fact is gone, the model provably cannot answer from the compressed text.
  A failure here is a real defect.
- If every fact survives, the model *can* still answer — but this does not prove
  it *will*. Restructuring can preserve every token and still make text harder
  to read.

So this is a floor, and it is labelled as one. Claiming it as "compression is
lossless for QA" would be exactly the kind of unearned number this file exists
to prevent. The sufficient version needs a model in the loop; `--model` does
that when you have an endpoint to point it at, and it is deliberately not part
of the nightly gate, because a gate that needs a paid API key is a gate that
gets switched off.

    python benchmarks/quality_eval.py
    python benchmarks/quality_eval.py --json results.json --min-retention 100
    python benchmarks/quality_eval.py --model gpt-4o --base-url http://localhost:7000/v1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field

from sensei.compression.router import ContentRouter, ContentType

# ─── Corpus ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Case:
    """One payload, and what has to survive compressing it."""

    name: str
    content: str
    # Strings that must still appear. Chosen to be the things an agent would
    # need to act: identifiers, error text, line numbers, values.
    facts: tuple[str, ...]
    # A question a model should be able to answer from the compressed text, and
    # the substring its answer must contain. Only used in --model mode.
    question: str = ""
    answer: str = ""
    force_type: ContentType | None = None


def _api_response() -> str:
    records = [
        {
            "id": 1000 + i,
            "sku": f"SKU-{i:04d}",
            "name": f"Widget {i}",
            "price_cents": 1999 + i * 37,
            "in_stock": i % 3 != 0,
            "warehouse": "eu-central-1" if i % 2 else "us-east-1",
            "self": f"https://api.example.com/products/{1000 + i}",
        }
        for i in range(24)
    ]
    return json.dumps({"products": records, "total": len(records)})


def _build_log() -> str:
    lines = [f"[{i:04d}] compiling module_{i}.cpp ... ok" for i in range(120)]
    lines.insert(
        73,
        "src/parser.cpp:412:19: error: no matching function for call to "
        "'Tokenizer::advance(std::string&, int)'",
    )
    lines.insert(74, "  note: candidate expects 1 argument, 2 provided")
    lines.append("2 errors generated.")
    lines.append("make: *** [Makefile:88: parser.o] Error 1")
    return "\n".join(lines)


def _stack_trace() -> str:
    return """\
Traceback (most recent call last):
  File "/app/worker.py", line 212, in run_batch
    results = [self.process(item) for item in batch]
  File "/app/worker.py", line 212, in <listcomp>
    results = [self.process(item) for item in batch]
  File "/app/worker.py", line 341, in process
    payload = self.serializer.encode(item.body)
  File "/app/serializers/json_fast.py", line 88, in encode
    return _dumps(obj, default=self._default)
TypeError: Object of type Decimal is not JSON serializable
"""


def _source() -> str:
    return '''\
"""Rate limiting for the gateway."""
import time
from collections import defaultdict


class TokenBucket:
    """A per-key token bucket.

    This docstring is long on purpose so that the compressor has something to
    remove, and it explains at length things that are obvious from the code.
    """

    def __init__(self, capacity: int = 60, refill_per_second: float = 1.0):
        # Store the capacity
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._tokens = defaultdict(lambda: float(capacity))
        self._last = defaultdict(time.monotonic)

    def allow(self, key: str, cost: int = 1) -> bool:
        now = time.monotonic()
        elapsed = now - self._last[key]
        self._last[key] = now
        self._tokens[key] = min(
            self.capacity, self._tokens[key] + elapsed * self.refill_per_second
        )
        if self._tokens[key] < cost:
            return False
        self._tokens[key] -= cost
        return True
'''


def _search_results() -> str:
    hits = [
        {"file": f"src/handlers/route_{i}.py", "line": 40 + i * 7, "match": "def handle("}
        for i in range(18)
    ]
    hits[11] = {"file": "src/handlers/auth.py", "line": 173, "match": "def handle_token_refresh("}
    return json.dumps(hits)


CORPUS: tuple[Case, ...] = (
    Case(
        name="json:api response",
        content=_api_response(),
        # An agent asked about a product needs the id, the sku and the price to
        # still be there. The `self` links are the redundancy worth dropping.
        facts=("SKU-0017", "1017", "2628", "eu-central-1"),
        question="What is the price_cents of SKU-0017?",
        answer="2628",
    ),
    Case(
        name="json:search results",
        content=_search_results(),
        facts=("src/handlers/auth.py", "173", "handle_token_refresh"),
        question="Which file and line defines handle_token_refresh?",
        answer="173",
    ),
    Case(
        name="logs:build failure",
        content=_build_log(),
        # The entire reason anyone reads a build log.
        facts=(
            "src/parser.cpp:412:19",
            "no matching function",
            "Tokenizer::advance",
            "Error 1",
        ),
        question="Which file and line does the compiler error point at?",
        answer="412",
    ),
    Case(
        name="logs:stack trace",
        content=_stack_trace(),
        facts=(
            "TypeError",
            "Decimal is not JSON serializable",
            "json_fast.py",
            "88",
            "encode",
        ),
        question="Which function raised, and what was the error?",
        answer="encode",
    ),
    Case(
        name="code:python",
        content=_source(),
        # Signatures and control flow must survive; the prose docstring is what
        # the compressor is supposed to remove.
        facts=(
            "class TokenBucket",
            "def allow",
            "refill_per_second",
            "self._tokens[key] -= cost",
        ),
        question="What is the default capacity of TokenBucket?",
        answer="60",
    ),
)


# ─── Fact retention ──────────────────────────────────────────────────────────


def _normalise(text: str) -> str:
    """Collapse whitespace so a fact split across a reflowed line still matches.

    Compression legitimately reflows and re-indents. A fact that survived but
    now has a different amount of space in it is retained, not lost, and
    reporting it as lost would train everyone to ignore this check.
    """
    return re.sub(r"\s+", " ", text)


@dataclass
class CaseResult:
    name: str
    content_type: str
    original_chars: int
    compressed_chars: int
    facts_total: int
    facts_kept: int
    missing: list[str] = field(default_factory=list)

    @property
    def retention_pct(self) -> float:
        return round(self.facts_kept / self.facts_total * 100, 1) if self.facts_total else 100.0


def evaluate(router: ContentRouter | None = None) -> dict:
    router = router or ContentRouter(enable_caching=False)
    results: list[CaseResult] = []

    for case in CORPUS:
        compressed = router.compress(case.content, force_type=case.force_type)
        haystack = _normalise(compressed.compressed)
        missing = [f for f in case.facts if _normalise(f) not in haystack]
        results.append(
            CaseResult(
                name=case.name,
                content_type=compressed.content_type.value,
                original_chars=len(case.content),
                compressed_chars=len(compressed.compressed),
                facts_total=len(case.facts),
                facts_kept=len(case.facts) - len(missing),
                missing=missing,
            )
        )

    total = sum(r.facts_total for r in results)
    kept = sum(r.facts_kept for r in results)
    orig = sum(r.original_chars for r in results)
    comp = sum(r.compressed_chars for r in results)

    return {
        "claim": (
            "necessary condition only: every required fact is still literally "
            "present after compression. Does not prove the model answers correctly."
        ),
        "cases": [
            {
                "name": r.name,
                "type": r.content_type,
                "facts_total": r.facts_total,
                "facts_kept": r.facts_kept,
                "retention_pct": r.retention_pct,
                "missing": r.missing,
                "size_reduction_pct": round((1 - r.compressed_chars / r.original_chars) * 100, 1),
            }
            for r in results
        ],
        "aggregate": {
            "facts_total": total,
            "facts_kept": kept,
            "retention_pct": round(kept / total * 100, 1) if total else 100.0,
            "size_reduction_pct": round((1 - comp / orig) * 100, 1) if orig else 0.0,
        },
    }


# ─── Optional: put a model in the loop ───────────────────────────────────────


def evaluate_with_model(model: str, base_url: str, api_key: str | None) -> dict:
    """Ask a real model the questions, against compressed context.

    This is the sufficient version of the check and it is opt-in: it needs an
    endpoint, it costs money per run, and a CI gate that requires a funded API
    key is a gate somebody eventually disables. Point it at a local Ollama
    through the gateway and it costs nothing.
    """
    import httpx

    router = ContentRouter(enable_caching=False)
    cases = [c for c in CORPUS if c.question and c.answer]
    outcomes = []

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    with httpx.Client(timeout=120.0) as client:
        for case in cases:
            compressed = router.compress(case.content, force_type=case.force_type)
            prompt = (
                "Answer using only the data below. Reply with the value alone, "
                "no explanation.\n\n"
                f"{compressed.compressed}\n\nQuestion: {case.question}"
            )
            try:
                resp = client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0,
                    },
                )
                resp.raise_for_status()
                reply = resp.json()["choices"][0]["message"]["content"]
            # Reported per case rather than aborting: one unreachable model
            # should not discard the answers already collected.
            except Exception as exc:
                outcomes.append({"name": case.name, "correct": False, "error": str(exc)})
                continue
            outcomes.append(
                {
                    "name": case.name,
                    "question": case.question,
                    "expected": case.answer,
                    "answer": reply.strip()[:200],
                    "correct": case.answer.lower() in reply.lower(),
                }
            )

    correct = sum(1 for o in outcomes if o.get("correct"))
    return {
        "model": model,
        "cases": outcomes,
        "aggregate": {
            "asked": len(outcomes),
            "correct": correct,
            "accuracy_pct": round(correct / len(outcomes) * 100, 1) if outcomes else 0.0,
        },
    }


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", metavar="PATH", help="write results here ('-' for stdout)")
    parser.add_argument(
        "--min-retention",
        type=float,
        default=None,
        metavar="PCT",
        help="exit non-zero below this fact-retention percentage (nightly uses 100)",
    )
    parser.add_argument("--model", help="also ask a real model the questions")
    parser.add_argument(
        "--base-url",
        default="http://localhost:7000/v1",
        help="OpenAI-compatible endpoint for --model (default: a local Sensei)",
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=None,
        metavar="PCT",
        help="with --model, exit non-zero below this answer accuracy",
    )
    args = parser.parse_args()

    data = evaluate()

    print("Fact retention after compression\n")
    print(f"{'case':<24}{'type':>7}{'kept':>10}{'retained':>10}{'smaller':>10}")
    print("-" * 61)
    for case in data["cases"]:
        print(
            f"{case['name']:<24}{case['type']:>7}"
            f"{case['facts_kept']}/{case['facts_total']:<8}"
            f"{case['retention_pct']:>9.0f}%{case['size_reduction_pct']:>9.0f}%"
        )
    agg = data["aggregate"]
    print("-" * 61)
    print(
        f"{'AGGREGATE':<24}{'':>7}{agg['facts_kept']}/{agg['facts_total']:<8}"
        f"{agg['retention_pct']:>9.0f}%{agg['size_reduction_pct']:>9.0f}%"
    )

    failures = [c for c in data["cases"] if c["missing"]]
    if failures:
        print("\nFacts lost:")
        for case in failures:
            for fact in case["missing"]:
                print(f"  {case['name']}: {fact!r}")

    print(f"\n{data['claim']}")

    if args.model:
        key = os.environ.get("OPENAI_API_KEY") or os.environ.get("SENSEI_API_KEY")
        model_data = evaluate_with_model(args.model, args.base_url, key)
        data["model_eval"] = model_data
        print(f"\nAnswer accuracy with {args.model}\n")
        for case in model_data["cases"]:
            mark = "ok " if case.get("correct") else "MISS"
            detail = case.get("error") or case.get("answer", "")
            print(f"  [{mark}] {case['name']:<24} {detail[:60]}")
        print(f"\n  {model_data['aggregate']['accuracy_pct']}% correct")

    if args.json:
        payload = json.dumps(data, indent=2)
        if args.json == "-":
            print(payload)
        else:
            with open(args.json, "w", encoding="utf-8") as handle:
                handle.write(payload + "\n")

    if args.min_retention is not None and agg["retention_pct"] < args.min_retention:
        print(
            f"\nFAIL: fact retention {agg['retention_pct']}% is below "
            f"the {args.min_retention}% floor",
            file=sys.stderr,
        )
        return 1
    if args.min_accuracy is not None and "model_eval" in data:
        accuracy = data["model_eval"]["aggregate"]["accuracy_pct"]
        if accuracy < args.min_accuracy:
            print(
                f"\nFAIL: answer accuracy {accuracy}% is below the {args.min_accuracy}% floor",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
