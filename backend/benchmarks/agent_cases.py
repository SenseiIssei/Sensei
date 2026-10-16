"""Fact-retention cases for coding-agent tool output.

Each payload has the shape of a real tool result an agent sees (grep, git,
cargo test, pytest, a diff, a directory listing, an API array, a fetched page),
and each fact is something an agent would act on. They run through
``ContentRouter.compress(edit_target=True)``, the path a gateway uses for tool
results, unless a case says otherwise.

Lossy compressors are allowed to cut here, with a marker; what they may not
cut is the line that matters.
"""

from __future__ import annotations

import json
from typing import Any


def _grep_multi() -> str:
    lines = []
    for f in range(6):
        path = f"src/services/billing/handler_{f}.py"
        for k in range(5):
            lines.append(f"{path}:{20 + k * 9}:    invoice = load_invoice(customer_id, period={k})")
    lines.insert(17, "src/services/billing/handler_3.py:61:    raise InvoiceError('period closed')")
    return "\n".join(lines)


def _grep_large() -> str:
    lines = []
    for f in range(40):
        for k in range(8):
            lines.append(
                f"crates/engine/src/module_{f:02d}.rs:{100 + k * 13}:        let value = "
                f"cache.get(&key_{k}).unwrap_or_default();"
            )
    lines[173] = 'crates/engine/src/module_21.rs:139:        panic!("cache poisoned: {key}");'
    return "\n".join(lines)


def _cargo_test() -> str:
    lines = ["   Compiling engine v0.4.2 (F:\\work\\engine)", "    Finished `test` profile in 12.31s",
             "     Running unittests src/lib.rs (target\\debug\\deps\\engine-3f2a)", "", "running 214 tests"]  # fmt: skip
    for i in range(214):
        name = f"tests::scheduler::case_{i:03d}"
        lines.append(f"test {name} ... {'FAILED' if i == 131 else 'ok'}")
    lines += [
        "",
        "failures:",
        "",
        "---- tests::scheduler::case_131 stdout ----",
        "thread 'tests::scheduler::case_131' panicked at src/scheduler.rs:88:9:",
        "assertion `left == right` failed: retry budget exhausted",
        "  left: 3",
        " right: 4",
        "",
        "failures:",
        "    tests::scheduler::case_131",
        "",
        "test result: FAILED. 213 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; "
        "finished in 0.84s",
    ]
    return "\n".join(lines)


def _pytest() -> str:
    rows = [f"tests/test_mod_{i:02d}.py ........................................ [{i * 4:3d}%]" for i in range(24)]  # fmt: skip
    rows.insert(11, "tests/test_ledger.py ......F................................. [ 46%]")
    return "\n".join(
        [
            "============================= test session starts =============================",
            "platform win32 -- Python 3.14.0, pytest-9.1.1, pluggy-1.6.0",
            "collected 1003 items",
            "",
            *rows,
            "",
            "================================== FAILURES ===================================",
            "_____________________ test_ledger_rounds_half_to_even _____________________",
            "",
            "    def test_ledger_rounds_half_to_even():",
            ">       assert ledger.round_cents(Decimal('2.675')) == Decimal('2.68')",
            "E       AssertionError: assert Decimal('2.67') == Decimal('2.68')",
            "",
            "tests/test_ledger.py:41: AssertionError",
            "=========================== short test summary info ===========================",
            "FAILED tests/test_ledger.py::test_ledger_rounds_half_to_even - AssertionError",
            "======================= 1 failed, 1002 passed in 38.20s ========================",
        ]
    )


def _git_status_log() -> str:
    return "\n".join(
        [
            "On branch feature/retry-budget",
            "Your branch is ahead of 'origin/feature/retry-budget' by 2 commits.",
            '  (use "git push" to publish your local commits)',
            "",
            "Changes not staged for commit:",
            '  (use "git add <file>..." to update what will be committed)',
            '  (use "git restore <file>..." to discard changes in working directory)',
            "\tmodified:   src/scheduler.rs",
            "\tmodified:   src/retry.rs",
            "",
            "Untracked files:",
            '  (use "git add <file>..." to include in what will be committed)',
            "\tsrc/budget.rs",
            "",
            'no changes added to commit (use "git add" and/or "git commit -a")',
        ]
    )


def _git_log() -> str:
    out = []
    for i in range(12):
        sha = f"{i:02x}" + "3f9a1c0b7d2e4a65b8c1d0e9f7a6b5c4d3e2f1"[:38]
        out += [
            f"commit {sha}",
            "Author: Dana Example <dana@example.com>",
            f"Date:   Thu Oct {i + 1} 12:{i:02d}:00 2026 +0200",
            "",
            f"    scheduler: change number {i}",
            "",
        ]
    out[4 * 6 + 4] = "    retry: stop counting the first attempt against the budget"
    return "\n".join(out)


def _diff() -> str:
    lines = ["diff --git a/src/retry.rs b/src/retry.rs", "index 3f9a1c0..b7d2e4a 100644",
             "--- a/src/retry.rs", "+++ b/src/retry.rs", "@@ -40,30 +40,31 @@ impl Retry {"]  # fmt: skip
    for i in range(14):
        lines.append(f"     let step_{i} = self.base * {i};")
    lines.append("-    if attempts >= self.budget {")
    lines.append("+    if attempts > self.budget {")
    lines.append('+        tracing::warn!(attempts, "retry budget exhausted");')
    for i in range(14):
        lines.append(f"     let tail_{i} = self.cap - {i};")
    lines += ["diff --git a/Cargo.lock b/Cargo.lock", "--- a/Cargo.lock", "+++ b/Cargo.lock",
              "@@ -1,40 +1,40 @@"]  # fmt: skip
    for i in range(40):
        lines.append(f'-version = "0.{i}.0"')
        lines.append(f'+version = "0.{i}.1"')
    return "\n".join(lines)


def _listing() -> str:
    files = []
    for d in ("src/components", "src/pages", "src/lib/api"):
        for i in range(14):
            files.append(f"{d}/Widget{i:02d}.tsx")
    files.append("src/pages/BillingSettings.tsx")
    return "\n".join(files)


def _api_logs_array() -> str:
    rows: list[dict[str, Any]] = [
        {
            "id": 50000 + i,
            "ts": f"2026-10-16T09:{i // 60:02d}:{i % 60:02d}Z",
            "level": "info",
            "route": "/v1/invoices",
            "status": 200,
            "ms": 30 + i % 7,
        }
        for i in range(240)
    ]
    rows[187] = {
        "id": 50187,
        "ts": "2026-10-16T09:03:07Z",
        "level": "error",
        "route": "/v1/invoices",
        "status": 503,
        "ms": 30012,
        "error": "upstream ledger timed out",
    }
    return json.dumps(rows)


def _html_page() -> str:
    nav = "".join(f'<li><a href="/docs/{i}">Section {i}</a></li>' for i in range(40))
    script = "var x=" + json.dumps({"k": list(range(6000))}) + ";"
    return f"""<!DOCTYPE html><html><head><title>Retry budgets</title>
<style>body{{font-family:sans-serif}} .nav{{display:flex}}</style><script>{script}</script></head>
<body><nav class="nav"><ul>{nav}</ul></nav><main><article>
<h1>Retry budgets</h1>
<p>A retry budget caps retries at <code>max_attempts = 4</code> per request.</p>
<p>See <a href="https://example.com/rfc/retry">the retry RFC</a> for the backoff curve.</p>
</article></main><footer>Copyright 2026</footer></body></html>"""


def _minified_grep() -> str:
    blob = "".join(f"function f{i}(a,b){{return a*{i}+b}}" for i in range(400))
    hit = 'e.prototype.refreshSession=function(t){return this.api.post("/session/refresh",t)}'
    return f"bundle.min.js:1:{blob[:6000]}{hit}{blob[6000:]}"


def _mixed() -> str:
    return "\n".join(
        [
            "On branch main",
            "nothing to commit, working tree clean",
            "",
            "src/a.rs",
            "src/b.rs",
            "src/c.rs",
            "src/lib/d.rs",
            "src/lib/e.rs",
            "",
            "pub fn budget(attempts: u32, cap: u32) -> bool {",
            "    // the first attempt is free",
            "    attempts <= cap",
            "}",
        ]
    )


def build(case: Any) -> tuple[Any, ...]:
    """The cases, built with quality_eval's ``Case`` (passed in to avoid a cycle)."""
    return (
        case(
            name="search:grep 6 files",
            content=_grep_multi(),
            facts=("raise InvoiceError('period closed')", "handler_3.py", "61:"),
            edit_target=True,
        ),
        case(
            name="search:grep 320 hits",
            content=_grep_large(),
            facts=('panic!("cache poisoned: {key}");', "module_21.rs", "139:"),
            edit_target=True,
            query="where does the cache get poisoned",
        ),
        case(
            name="test:cargo 1 of 214 failed",
            content=_cargo_test(),
            facts=(
                "tests::scheduler::case_131",
                "src/scheduler.rs:88:9",
                "retry budget exhausted",
                "213 passed; 1 failed",
            ),
            edit_target=True,
        ),
        case(
            name="test:pytest 1 failure",
            content=_pytest(),
            facts=(
                "test_ledger_rounds_half_to_even",
                "tests/test_ledger.py:41",
                "Decimal('2.67') == Decimal('2.68')",
                "1 failed, 1002 passed",
            ),
            edit_target=True,
        ),
        case(
            name="git:status",
            content=_git_status_log(),
            facts=(
                "feature/retry-budget",
                "src/scheduler.rs",
                "src/retry.rs",
                "src/budget.rs",
                "ahead of 'origin/feature/retry-budget' by 2 commits",
            ),
            edit_target=True,
        ),
        case(
            name="git:log",
            content=_git_log(),
            facts=("retry: stop counting the first attempt", "dana@example.com", "Oct 5"),
            edit_target=True,
        ),
        case(
            name="diff:code + lockfile",
            content=_diff(),
            facts=(
                "-    if attempts >= self.budget {",
                "+    if attempts > self.budget {",
                '"retry budget exhausted"',
                "Cargo.lock",
            ),
            edit_target=True,
        ),
        case(
            name="listing:find",
            content=_listing(),
            facts=("src/pages/", "BillingSettings.tsx", "src/lib/api/", "Widget13.tsx"),
            edit_target=True,
        ),
        case(
            name="json:240 log records",
            content=_api_logs_array(),
            facts=("50187", "upstream ledger timed out", "503", "30012"),
            edit_target=True,
        ),
        case(
            name="html:fetched page",
            content=_html_page(),
            facts=("Retry budgets", "max_attempts = 4", "https://example.com/rfc/retry"),
            edit_target=True,
        ),
        case(
            name="dense:grep in bundle",
            content=_minified_grep(),
            facts=('refreshSession=function(t){return this.api.post("/session/refresh",t)}',),
            edit_target=True,
            query="where is refreshSession defined",
        ),
        case(
            name="mixed:status+ls+code",
            content=_mixed(),
            facts=(
                "pub fn budget(attempts: u32, cap: u32) -> bool {",
                "    // the first attempt is free",
                "nothing to commit",
            ),
            edit_target=True,
        ),
    )
