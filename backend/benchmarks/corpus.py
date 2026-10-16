# Synthetic data, not security: the RNG is seeded on purpose, the hashes only
# make fake commit ids, and the box-drawing glyphs are what vitest prints.
# ruff: noqa: S311, S324, RUF001
"""A seeded, synthetic corpus of what coding agents actually read.

The old benchmark corpus was six hand-written samples, and the headline it
produced (79%) said more about those six samples than about anybody's bill. A
real Claude Code session is mostly shell output — `git`, `grep`, test runs,
directory listings — plus file reads that must reach the model byte-exact,
because the model edits them next by exact string match.

This module generates that traffic. Everything is synthetic: a fictional
project ("acme-shop"), fictional people, fictional ids. No transcript, no file
from anybody's disk, no network. The same seed produces byte-identical text on
every machine, and `corpus_digest()` proves it — the digest is recorded next to
every published number.

Two groups:

* ``agent``    — the tool outputs of an everyday coding-agent session, one or
  more samples per kind (see ``KINDS``).
* ``headroom:*`` — four scenarios with the same shape and sizes as Headroom's
  published "proof" table (code search with 100 results, an SRE incident,
  codebase exploration, issue triage), so the two projects can be compared on
  the scenarios Headroom chose. The generators are written from scratch here;
  only the scenario shapes follow Headroom's ``real_world_agent_benchmark.py``.

Every sample carries the ``facts`` an agent would need out of it. A compressor
that drops one of them has made the payload useless for the task, whatever the
token count says.

    python -m benchmarks.corpus            # list the corpus and its digest
    python -m benchmarks.corpus --dump DIR # write every sample to DIR to inspect
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import dataclass, replace
from pathlib import Path

#: Changing the seed changes every number derived from this corpus. Any figure
#: quoted anywhere must name the seed (and the digest) it came from.
DEFAULT_SEED = 20261016


@dataclass(frozen=True)
class Sample:
    """One tool output as the model would receive it."""

    name: str
    kind: str
    group: str
    tool: str
    text: str
    # Literal strings an agent must still be able to read after compression.
    facts: tuple[str, ...] = ()
    # File reads: the model edits these next by exact match, so any change at
    # all is a defect, however many tokens it saves.
    byte_exact: bool = False
    # For the optional model-in-the-loop check (quality_eval --model).
    question: str = ""
    answer: str = ""


#: Human labels, in the order the README lists them.
KINDS: dict[str, str] = {
    "grep": "grep / rg results",
    "git_log": "git log",
    "git_diff": "git diff",
    "git_status": "git status",
    "test_pytest": "pytest output",
    "test_js": "npm / vitest output",
    "build_cargo": "cargo build",
    "build_ci": "CI / docker build log",
    "pkg_install": "pip / npm install",
    "listing": "ls / find / tree",
    "kubectl": "kubectl tables",
    "json_api": "JSON API responses",
    "mcp": "MCP tool results",
    "file_read": "file reads (Read tool)",
    "cat_source": "cat of source / config",
    "web_page": "web pages (WebFetch)",
    "stack_trace": "stack traces",
    "prose": "prose docs",
}


# ─── A fictional project for everything to talk about ────────────────────────

_FIRST = [
    "Ada",
    "Moreau",
    "Lin",
    "Okafor",
    "Priya",
    "Raman",
    "Tomás",
    "Silva",
    "Mei",
    "Tanaka",
    "Jonas",
    "Berg",
    "Amara",
    "Diallo",
    "Kai",
    "Novak",
    "Sofia",
    "Rossi",
    "Elif",
    "Kaya",
    "Noah",
    "Fischer",
    "Yara",
    "Haddad",
    "Leo",
    "Schmidt",
    "Ines",
    "Duarte",
    "Omar",
    "Farouk",
    "Hana",
    "Kim",
]
_FIRST = [" ".join(_FIRST[i : i + 2]) for i in range(0, len(_FIRST), 2)]

_PY_PKGS = ("auth", "cart", "billing", "catalog", "orders", "search", "notify", "ledger")
_PY_MODS = (
    "service",
    "models",
    "routes",
    "repository",
    "schemas",
    "tasks",
    "client",
    "cache",
    "validators",
    "events",
)
_TS_DIRS = ("components", "hooks", "pages", "lib", "api", "store", "utils")
_TS_FILES = (
    "CartDrawer",
    "CheckoutForm",
    "ProductCard",
    "SearchBar",
    "useSession",
    "useCart",
    "formatPrice",
    "apiClient",
    "OrderTable",
    "Toast",
    "AddressForm",
    "PriceTag",
)
_VERBS = ("get", "list", "create", "update", "delete", "sync", "refresh", "validate", "apply")
_NOUNS = (
    "session",
    "token",
    "cart",
    "order",
    "invoice",
    "product",
    "refund",
    "coupon",
    "customer",
    "payment",
    "webhook",
    "shipment",
)
_SUBJECTS = (
    "fix race in token refresh",
    "add idempotency keys to payment webhooks",
    "cache product search results for 60s",
    "drop python 3.10 support",
    "split cart totals into tax and shipping",
    "retry shipment sync on 503",
    "make coupon validation case-insensitive",
    "log request ids in the billing worker",
    "bump vite to 8.1 and fix the dev proxy",
    "remove the legacy v1 orders endpoint",
    "paginate the invoice list",
    "handle empty addresses in checkout",
    "move ledger rounding into one place",
    "add an index on orders.created_at",
    "stop double-sending order confirmation emails",
    "rename refresh_window to refresh_grace_seconds",
)
_PREFIXES = ("feat", "fix", "chore", "refactor", "perf", "test", "docs")


class _Project:
    """Names, paths and people for one fictional repository."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.people = [(n, n.split()[0].lower() + "@acme.dev") for n in _FIRST]
        self.py_files = [f"src/acme/{p}/{m}.py" for p in _PY_PKGS for m in _PY_MODS]
        self.test_files = [f"tests/{p}/test_{m}.py" for p in _PY_PKGS for m in _PY_MODS[:5]]
        self.ts_files = [
            f"web/src/{d}/{f}.{'tsx' if f[0].isupper() else 'ts'}"
            for d in _TS_DIRS
            for f in _TS_FILES
        ]
        self.functions = [f"{v}_{n}" for v in _VERBS for n in _NOUNS]

    def sha(self) -> str:
        return hashlib.sha1(str(self.rng.random()).encode()).hexdigest()

    def person(self) -> tuple[str, str]:
        return self.rng.choice(self.people)

    def func(self) -> str:
        return self.rng.choice(self.functions)


# ─── Source code (also used inside diffs, reads and greps) ───────────────────


def _py_function(rng: random.Random, name: str, noun: str) -> list[str]:
    arg = rng.choice(("request", "payload", "ctx", "item", "record"))
    body = rng.choice(
        (
            [
                f"    {noun} = self.repo.get({arg}.id)",
                f"    if {noun} is None:",
                f'        raise NotFound(f"{noun} {{{arg}.id}} does not exist")',
                f"    {noun}.updated_at = utcnow()",
                f"    self.repo.save({noun})",
                f"    return {noun}",
            ],
            [
                "    started = time.monotonic()",
                "    try:",
                f'        result = await self.client.post(f"/{noun}s/{{{arg}.id}}", json={arg}.dict())',
                "    except httpx.TimeoutException:",
                f'        log.warning("{name} timed out after %.1fs", time.monotonic() - started)',
                "        raise",
                "    result.raise_for_status()",
                "    return result.json()",
            ],
            [
                f"    # Validate before touching the database: a bad {noun} must not",
                "    # leave a half-written row behind.",
                f"    errors = validate_{noun}({arg})",
                "    if errors:",
                "        raise ValidationError(errors)",
                "    with self.db.transaction():",
                f"        row = self.repo.insert({arg})",
                f'        self.events.publish("{noun}.created", row.id)',
                "    return row",
            ],
            [
                "    total = Decimal(0)",
                f"    for line in {arg}.lines:",
                "        if line.quantity <= 0:",
                "            continue",
                "        total += line.unit_price * line.quantity",
                '    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)',
            ],
        )
    )
    is_async = "await" in "".join(body)
    head = f"{'async ' if is_async else ''}def {name}(self, {arg}: {noun.title()}Request) -> {noun.title()}:"
    doc = f'    """{name.replace("_", " ").capitalize()} and return the stored {noun}."""'
    return ["    " + head, "    " + doc, *["    " + b for b in body], ""]


def python_module(rng: random.Random, proj: _Project, path: str, n_funcs: int = 8) -> str:
    pkg = path.split("/")[-2]
    noun = rng.choice(_NOUNS)
    cls = f"{noun.title()}{rng.choice(('Service', 'Manager', 'Repository', 'Handler'))}"
    lines = [
        f'"""{pkg.title()} {path.rsplit("/", 1)[-1][:-3]}: the {noun} workflow.',
        "",
        f"Everything that reads or writes a {noun} goes through {cls}, so the",
        "invariants below hold in one place instead of at every call site.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "import logging",
        "import time",
        "from dataclasses import dataclass",
        "from decimal import ROUND_HALF_EVEN, Decimal",
        "",
        "import httpx",
        "",
        f"from acme.{pkg}.errors import NotFound, ValidationError",
        f"from acme.{pkg}.repository import Repository",
        "from acme.common.clock import utcnow",
        "",
        "log = logging.getLogger(__name__)",
        "",
        f"DEFAULT_TIMEOUT = {rng.choice((5, 10, 15, 30))}.0",
        f"MAX_RETRIES = {rng.randint(2, 6)}",
        "",
        "",
        "@dataclass",
        f"class {noun.title()}Config:",
        f'    """Tunables for {cls}."""',
        "",
        "    timeout: float = DEFAULT_TIMEOUT",
        "    retries: int = MAX_RETRIES",
        "    tags: list[str] = field(default_factory=list)",
        "",
        "",
        f"class {cls}:",
        f'    """Owns the lifecycle of a {noun}."""',
        "",
        f"    def __init__(self, repo: Repository, client: httpx.AsyncClient, config: {noun.title()}Config | None = None):",
        "        self.repo = repo",
        "        self.client = client",
        f"        self.config = config or {noun.title()}Config()",
        "",
    ]
    used = set()
    for _ in range(n_funcs):
        name = f"{rng.choice(_VERBS)}_{noun}"
        while name in used:
            name = f"{rng.choice(_VERBS)}_{noun}_{rng.choice(('batch', 'async', 'safe', 'now'))}"
        used.add(name)
        lines += _py_function(rng, name, noun)
    return "\n".join(lines).rstrip() + "\n"


def ts_module(rng: random.Random, name: str) -> str:
    noun = rng.choice(_NOUNS)
    comp = name[0].isupper()
    lines = [
        "import { useEffect, useMemo, useState } from 'react';",
        "import { z } from 'zod';",
        "import { apiClient } from '../lib/apiClient';",
        f"import type {{ {noun.title()} }} from '../types';",
        "",
        f"const {noun.title()}Schema = z.object({{",
        "  id: z.string().uuid(),",
        "  createdAt: z.string().datetime(),",
        "  amountCents: z.number().int().nonnegative(),",
        "  currency: z.enum(['EUR', 'USD', 'GBP']),",
        "});",
        "",
    ]
    if comp:
        lines += [
            f"export interface {name}Props {{",
            f"  {noun}Id: string;",
            "  onClose?: () => void;",
            "  compact?: boolean;",
            "}",
            "",
            f"export function {name}({{ {noun}Id, onClose, compact = false }}: {name}Props) {{",
            f"  const [{noun}, set{noun.title()}] = useState<{noun.title()} | null>(null);",
            "  const [error, setError] = useState<string | null>(null);",
            "",
            "  useEffect(() => {",
            "    let cancelled = false;",
            f"    apiClient.get(`/{noun}s/${{{noun}Id}}`)",
            f"      .then((res) => {noun.title()}Schema.parse(res.data))",
            f"      .then((value) => {{ if (!cancelled) set{noun.title()}(value); }})",
            "      .catch((err: Error) => setError(err.message));",
            "    return () => { cancelled = true; };",
            f"  }}, [{noun}Id]);",
            "",
            "  const label = useMemo(",
            f"    () => ({noun} ? formatMoney({noun}.amountCents, {noun}.currency) : '…'),",
            f"    [{noun}],",
            "  );",
            "",
            '  if (error) return <p role="alert">{error}</p>;',
            "  return (",
            f"    <section className={{compact ? 'card card--compact' : 'card'}} aria-label=\"{noun}\">",
            "      <h2>{label}</h2>",
            "      {onClose && <button onClick={onClose}>Close</button>}",
            "    </section>",
            "  );",
            "}",
        ]
    else:
        lines += [
            f"export async function {name}(id: string, signal?: AbortSignal): Promise<{noun.title()}> {{",
            f"  const res = await apiClient.get(`/{noun}s/${{id}}`, {{ signal }});",
            f"  return {noun.title()}Schema.parse(res.data);",
            "}",
            "",
            "export function formatMoney(cents: number, currency: string): string {",
            "  return new Intl.NumberFormat('en', { style: 'currency', currency }).format(cents / 100);",
            "}",
        ]
    for i in range(rng.randint(3, 7)):
        fn = f"{rng.choice(_VERBS)}{rng.choice(_NOUNS).title()}{i}"
        lines += [
            "",
            f"// {fn}: keeps the {noun} list sorted by creation date, newest first.",
            f"export function {fn}(items: {noun.title()}[]): {noun.title()}[] {{",
            "  return [...items].sort((a, b) => b.createdAt.localeCompare(a.createdAt));",
            "}",
        ]
    return "\n".join(lines) + "\n"


# ─── Shell output ────────────────────────────────────────────────────────────


def grep_output(rng: random.Random, proj: _Project, hits: int) -> tuple[str, tuple[str, ...]]:
    """`grep -rn` across a repository: a few hot files, many matches each."""
    term = rng.choice(proj.functions)
    files = rng.sample(proj.py_files + proj.test_files, 18)
    weights = [rng.paretovariate(1.2) for _ in files]
    rows: dict[str, set[int]] = {}
    for _ in range(hits):
        f = rng.choices(files, weights)[0]
        rows.setdefault(f, set()).add(rng.randint(5, 900))
    shapes = (
        "    result = {t}(request)",
        "    return await self.{t}(payload)",
        "        {t}(item, force=True)",
        "from acme.common import {t}",
        "    assert {t}(fixture) is not None",
        '    log.debug("calling {t} for %s", key)',
        "            await service.{t}(ctx, retries=3)",
        "    # {t} is idempotent; safe to retry",
    )
    out = []
    for f in sorted(rows):
        for line in sorted(rows[f]):
            text = rng.choice(shapes).format(t=term)
            out.append(f"{f}:{line}:{text}")
    # The definition is what the agent was looking for.
    def_file = rng.choice(sorted(rows))
    target = f"{def_file}:{rng.randint(10, 60)}:    def {term}(self, request):"
    out.insert(rng.randint(0, len(out)), target)
    return "\n".join(out) + "\n", (
        target.split(":", 2)[0] + ":" + target.split(":", 2)[1],
        f"def {term}",
    )


def rg_context(rng: random.Random, proj: _Project, files: int) -> tuple[str, tuple[str, ...]]:
    """`rg -n -C2 --heading` — grouped matches with surrounding context."""
    term = rng.choice(proj.functions)
    out = []
    picked = rng.sample(proj.py_files, files)
    for f in picked:
        out.append(f)
        src = python_module(rng, proj, f, 4).split("\n")
        for _ in range(rng.randint(1, 4)):
            at = rng.randint(3, len(src) - 4)
            for j in range(at - 2, at + 3):
                sep = ":" if j == at else "-"
                if j == at:
                    indent = len(src[j]) - len(src[j].lstrip()) or 8
                    text = " " * indent + f"result = await self.{term}(ctx)"
                else:
                    text = src[j]
                out.append(f"{j + 1}{sep}{text}")
            out.append("--")
        out[-1] = ""
    return "\n".join(out), (picked[0], term)


def git_log(rng: random.Random, proj: _Project, n: int, stat: bool) -> tuple[str, tuple[str, ...]]:
    out = []
    day = 14
    facts: list[str] = []
    for i in range(n):
        sha = proj.sha()
        name, email = proj.person()
        subj = f"{rng.choice(_PREFIXES)}({rng.choice(_PY_PKGS)}): {rng.choice(_SUBJECTS)}"
        hh, mm, ss = rng.randint(8, 22), rng.randint(0, 59), rng.randint(0, 59)
        if rng.random() < 0.3:
            day = max(1, day - 1)
        out += [
            f"commit {sha}",
            *([f"Merge: {sha[:7]} {proj.sha()[:7]}"] if rng.random() < 0.1 else []),
            f"Author: {name} <{email}>",
            f"Date:   {('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[day % 7]} Oct {day} {hh:02d}:{mm:02d}:{ss:02d} 2026 +0200",
            "",
            f"    {subj}",
        ]
        if rng.random() < 0.6:
            out += [
                "",
                f"    The previous behaviour {rng.choice(('dropped', 'duplicated', 'delayed'))} "
                f"{rng.choice(_NOUNS)}s when the upstream returned {rng.choice((409, 429, 503))}.",
                f"    Closes #{rng.randint(100, 2400)}.",
            ]
        if stat:
            files = rng.sample(proj.py_files + proj.ts_files, rng.randint(1, 6))
            out.append("")
            adds = 0
            for f in files:
                k = rng.randint(1, 80)
                adds += k
                plus = rng.randint(0, k)
                bar = "+" * min(plus, 40) + "-" * min(k - plus, 40)
                out.append(f" {f:<52} | {k:>3} {bar}")
            out.append(
                f" {len(files)} files changed, {adds} insertions(+), {rng.randint(0, adds)} deletions(-)"
            )
        out.append("")
        if i == n // 3:
            facts = [sha, subj]
    return "\n".join(out), tuple(facts)


def git_diff(
    rng: random.Random, proj: _Project, files: int, lockfile: bool
) -> tuple[str, tuple[str, ...]]:
    out = []
    facts: list[str] = []
    for f in rng.sample(proj.py_files, files):
        src = python_module(rng, proj, f, 5).split("\n")
        out += [
            f"diff --git a/{f} b/{f}",
            f"index {proj.sha()[:9]}..{proj.sha()[:9]} 100644",
            f"--- a/{f}",
            f"+++ b/{f}",
        ]
        at = 1
        for _ in range(rng.randint(1, 3)):
            at = rng.randint(at, max(at, len(src) - 12))
            ctx = src[at : at + 7]
            new = f"    if retries > self.config.retries:  # was: {rng.randint(1, 5)}"
            out.append(f"@@ -{at + 1},7 +{at + 1},8 @@ class {rng.choice(_NOUNS).title()}Service:")
            out += [" " + c for c in ctx[:3]]
            out.append("-" + ctx[3])
            out.append("+" + ctx[3].replace("self.repo", "self._repo"))
            out.append("+" + new)
            out += [" " + c for c in ctx[4:7]]
            if not facts:
                facts = [f"+++ b/{f}", new.strip()]
            at += 8
    if lockfile:
        out += [
            "diff --git a/web/package-lock.json b/web/package-lock.json",
            f"index {proj.sha()[:9]}..{proj.sha()[:9]} 100644",
            "--- a/web/package-lock.json",
            "+++ b/web/package-lock.json",
        ]
        for i in range(60):
            pkg = rng.choice(
                (
                    "@babel/core",
                    "esbuild",
                    "rollup",
                    "postcss",
                    "vite",
                    "@types/node",
                    "semver",
                    "picomatch",
                )
            )
            at = 1000 + i * 37
            v_old = f"{rng.randint(1, 9)}.{rng.randint(0, 30)}.{rng.randint(0, 20)}"
            v_new = f"{v_old.split('.', maxsplit=1)[0]}.{rng.randint(0, 30)}.{rng.randint(0, 20)}"
            h = hashlib.sha512(str(rng.random()).encode()).hexdigest()[:86]
            out += [
                f"@@ -{at},9 +{at},9 @@",
                f'     "node_modules/{pkg}": {{',
                f'-      "version": "{v_old}",',
                f'-      "resolved": "https://registry.npmjs.org/{pkg}/-/{pkg.split("/")[-1]}-{v_old}.tgz",',
                f'-      "integrity": "sha512-{h}==",',
                f'+      "version": "{v_new}",',
                f'+      "resolved": "https://registry.npmjs.org/{pkg}/-/{pkg.split("/")[-1]}-{v_new}.tgz",',
                f'+      "integrity": "sha512-{h[::-1]}==",',
                '       "dev": true,',
                '       "license": "MIT",',
            ]
    return "\n".join(out) + "\n", tuple(facts)


def git_status(rng: random.Random, proj: _Project, n: int) -> tuple[str, tuple[str, ...]]:
    mod = rng.sample(proj.py_files + proj.ts_files, n)
    new = rng.sample(proj.test_files, max(2, n // 3))
    out = [
        f"On branch feature/{rng.choice(_NOUNS)}-{rng.choice(_VERBS)}",
        "Your branch is ahead of 'origin/main' by 3 commits.",
        '  (use "git push" to publish your local commits)',
        "",
        "Changes to be committed:",
        '  (use "git restore --staged <file>..." to unstage)',
        f"\tmodified:   {mod[0]}",
        "",
        "Changes not staged for commit:",
        '  (use "git add <file>..." to update what will be committed)',
        '  (use "git restore <file>..." to discard changes in working directory)',
        *[f"\t{'deleted: ' if rng.random() < 0.1 else 'modified:'}   {m}" for m in mod[1:]],
        "",
        "Untracked files:",
        '  (use "git add <file>..." to include in what will be committed)',
        *[f"\t{t}" for t in new],
        "",
        'no changes added to commit (use "git add" and/or "git commit -a")',
    ]
    return "\n".join(out) + "\n", (mod[0], new[0])


def pytest_output(rng: random.Random, proj: _Project, verbose: bool) -> tuple[str, tuple[str, ...]]:
    files = rng.sample(proj.test_files, 16)
    total = 0
    out = [
        "============================= test session starts ==============================",
        "platform linux -- Python 3.12.7, pytest-9.1.1, pluggy-1.6.0",
        "rootdir: /home/dev/acme-shop",
        "configfile: pyproject.toml",
        "plugins: asyncio-1.4.0, cov-7.1.0, xdist-3.8.0",
        "asyncio: mode=Mode.STRICT, default_loop_scope=function",
        f"collected {rng.randint(300, 600)} items",
        "",
    ]
    fail_file = files[5]
    fail_test = f"test_{rng.choice(_VERBS)}_{rng.choice(_NOUNS)}_{rng.choice(('rotates', 'rounds', 'retries', 'rejects'))}"
    for f in files:
        k = rng.randint(8, 40)
        total += k
        if verbose:
            for j in range(k):
                name = (
                    fail_test
                    if (f == fail_file and j == 3)
                    else f"test_{rng.choice(_VERBS)}_{rng.choice(_NOUNS)}_{j}"
                )
                status = (
                    "FAILED" if name == fail_test else rng.choice(("PASSED",) * 30 + ("SKIPPED",))
                )
                out.append(
                    f"{f}::{name} {status}{' ' * max(1, 58 - len(f) - len(name))}[{min(99, total * 100 // 520):>3}%]"
                )
        else:
            dots = "".join(
                "F" if (f == fail_file and j == 3) else rng.choice("." * 40 + "s") for j in range(k)
            )
            out.append(
                f"{f} {dots}{' ' * max(1, 70 - len(f) - k)}[{min(99, total * 100 // 520):>3}%]"
            )
    exp, got = f"tok_{proj.sha()[:6]}", f"tok_{proj.sha()[:6]}"
    out += [
        "",
        "=================================== FAILURES ===================================",
        f"{'_' * 20} {fail_test} {'_' * 20}",
        "",
        "client = <starlette.testclient.TestClient object at 0x7f3a9c2b1d90>",
        "session_factory = <function session_factory.<locals>.make at 0x7f3a9c1e0ae0>",
        "",
        f"    async def {fail_test}(client, session_factory):",
        "        old = session_factory(expires_in=1)",
        '        resp = client.post("/auth/refresh", json={"token": old.refresh_token})',
        "        assert resp.status_code == 200",
        "        new = resp.json()",
        f'>       assert new["token"] == "{exp}"',
        f"E       AssertionError: assert '{got}' == '{exp}'",
        "E         ",
        f"E         - {exp}",
        f"E         + {got}",
        "",
        f"{fail_file}:{rng.randint(20, 300)}: AssertionError",
        "------------------------------ Captured log call -------------------------------",
        *[
            f"WARNING  acme.auth.service:service.py:{rng.randint(40, 300)} refresh retried ({i}/3) after 503"
            for i in range(1, 4)
        ],
        "=============================== warnings summary ===============================",
        *[
            f"{rng.choice(proj.test_files)}:{rng.randint(1, 200)}\n  DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).\n"
            for _ in range(rng.randint(3, 8))
        ],
        "-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html",
        "=========================== short test summary info ============================",
        f"FAILED {fail_file}::{fail_test} - AssertionError: assert '{got}' == '{exp}'",
        f"=================== 1 failed, {total - 3} passed, 2 skipped, 6 warnings in {rng.uniform(5, 40):.2f}s ===================",
    ]
    return "\n".join(out) + "\n", (f"{fail_file}::{fail_test}", "AssertionError", exp)


def vitest_output(rng: random.Random, proj: _Project) -> tuple[str, tuple[str, ...]]:
    files = rng.sample(proj.ts_files, 30)
    fail = files[7].replace(".tsx", ".test.tsx").replace(".ts", ".test.ts")
    out = ["", " RUN  v4.1.2 /home/dev/acme-shop/web", ""]
    tests = 0
    for f in files:
        t = f.replace(".tsx", ".test.tsx").replace(".ts", ".test.ts")
        k = rng.randint(2, 25)
        tests += k
        if t == fail:
            out += [
                f" ❯ {t} ({k} tests | 1 failed) {rng.randint(5, 90)}ms",
                f"   × computes tax for EU carts {rng.randint(1, 9)}ms",
            ]
        else:
            out.append(f" ✓ {t} ({k} tests) {rng.randint(2, 120)}ms")
    line = rng.randint(20, 90)
    out += [
        "",
        "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯",
        "",
        f" FAIL  {fail} > totals > computes tax for EU carts",
        "AssertionError: expected 119.99 to be 120 // Object.is equality",
        "",
        "- Expected",
        "+ Received",
        "",
        "- 120",
        "+ 119.99",
        "",
        f" ❯ {fail}:{line}:27",
        f"     {line - 2}|   const cart = makeCart([{{ sku: 'SKU-1', price: 99.99, qty: 1 }}]);",
        f"     {line - 1}|   cart.country = 'DE';",
        f"     {line}|   expect(total(cart)).toBe(120);",
        "       |                           ^",
        f"     {line + 1}| }});",
        "",
        "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/1]⎯",
        "",
        f" Test Files  1 failed | {len(files) - 1} passed ({len(files)})",
        f"      Tests  1 failed | {tests - 1} passed ({tests})",
        "   Start at  18:22:05",
        f"   Duration  {rng.uniform(2, 9):.2f}s (transform 1.21s, setup 0ms, collect 4.02s, tests 1.88s, environment 6.10s, prepare 2.33s)",
        "",
    ]
    return "\n".join(out), (f"{fail}:{line}:27", "expected 119.99 to be 120")


_CRATES = [
    "proc-macro2",
    "unicode-ident",
    "quote",
    "syn",
    "serde",
    "serde_derive",
    "libc",
    "cfg-if",
    "memchr",
    "itoa",
    "ryu",
    "once_cell",
    "log",
    "bytes",
    "pin-project-lite",
    "futures-core",
    "tokio-macros",
    "mio",
    "socket2",
    "tokio",
    "smallvec",
    "scopeguard",
    "lock_api",
    "parking_lot_core",
    "parking_lot",
    "hashbrown",
    "indexmap",
    "thiserror-impl",
    "thiserror",
    "anyhow",
    "regex-syntax",
    "aho-corasick",
    "regex-automata",
    "regex",
    "tracing-core",
    "tracing-attributes",
    "tracing",
    "http",
    "httparse",
    "h2",
    "hyper",
    "tower-service",
    "rustls",
    "ring",
    "untrusted",
    "webpki",
    "serde_json",
    "url",
    "percent-encoding",
    "form_urlencoded",
    "idna",
    "time",
    "chrono",
    "uuid",
    "rand_core",
    "rand_chacha",
    "rand",
    "getrandom",
    "base64",
    "sha2",
    "digest",
]


def cargo_build(rng: random.Random) -> tuple[str, tuple[str, ...]]:
    out = []
    for c in _CRATES:
        out.append(
            f"   Compiling {c} v{rng.randint(0, 2)}.{rng.randint(0, 30)}.{rng.randint(0, 40)}"
        )
    line = rng.randint(80, 300)
    out += [
        "   Compiling acme-core v0.4.0 (/home/dev/acme-shop/crates/core)",
        "warning: unused import: `std::collections::HashMap`",
        " --> crates/core/src/lib.rs:3:5",
        "  |",
        "3 | use std::collections::HashMap;",
        "  |     ^^^^^^^^^^^^^^^^^^^^^^^^^",
        "  |",
        "  = note: `#[warn(unused_imports)]` on by default",
        "",
        "error[E0308]: mismatched types",
        f"   --> crates/core/src/ledger.rs:{line}:26",
        "    |",
        f"{line} |         let total: u64 = entries.iter().map(|e| e.amount).sum::<i64>();",
        "    |                    ---   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ expected `u64`, found `i64`",
        "    |                    |",
        "    |                    expected due to this",
        "    |",
        "help: you can convert an `i64` to a `u64` and panic if the converted value doesn't fit",
        "    |",
        f"{line} |         let total: u64 = entries.iter().map(|e| e.amount).sum::<i64>().try_into().unwrap();",
        "    |                                                                       ++++++++++++++++++++",
        "",
        "For more information about this error, try `rustc --explain E0308`.",
        "warning: `acme-core` (lib) generated 1 warning",
        "error: could not compile `acme-core` (lib) due to 1 previous error; 1 warning emitted",
    ]
    return "\n".join(out) + "\n", (
        "error[E0308]",
        f"crates/core/src/ledger.rs:{line}:26",
        "expected `u64`, found `i64`",
    )


def ci_log(rng: random.Random, proj: _Project, steps: int) -> tuple[str, tuple[str, ...]]:
    """A GitHub Actions job log: ISO timestamps on every line, one real error."""
    t = 0.0
    out = []

    def stamp() -> str:
        nonlocal t
        t += rng.uniform(0.001, 0.9)
        s = int(t)
        return f"2026-10-14T18:{22 + s // 60:02d}:{s % 60:02d}.{int((t % 1) * 1e7):07d}Z"

    out.append(f"{stamp()} ##[group]Run actions/checkout@v7")
    out.append(f"{stamp()} Syncing repository: acme/acme-shop")
    out.append(f"{stamp()} ##[endgroup]")
    for i in range(steps):
        pkg = rng.choice(_CRATES + list(_PY_PKGS))
        out.append(
            f"{stamp()} #{12 + i} [build {i + 1}/{steps}] RUN pip install --no-cache-dir {pkg}"
        )
        for _ in range(rng.randint(2, 6)):
            out.append(
                f"{stamp()} #{12 + i} {t:.3f} Collecting {rng.choice(_CRATES)}>={rng.randint(1, 9)}.{rng.randint(0, 9)}"
            )
        out.append(f"{stamp()} #{12 + i} DONE {rng.uniform(0.1, 20):.1f}s")
    err = f'src/acme/{rng.choice(_PY_PKGS)}/models.py:{rng.randint(10, 400)}: error: Incompatible return value type (got "str | None", expected "str")  [return-value]'
    out += [
        f"{stamp()} ##[group]Run mypy src",
        f"{stamp()} {err}",
        f"{stamp()} Found 1 error in 1 file (checked 214 source files)",
        f"{stamp()} ##[error]Process completed with exit code 1.",
        f"{stamp()} ##[endgroup]",
        f"{stamp()} Post job cleanup.",
    ]
    return "\n".join(out) + "\n", (
        err.split(": error", maxsplit=1)[0],
        "Incompatible return value type",
        "exit code 1",
    )


def pip_install(rng: random.Random, proj: _Project, n: int) -> tuple[str, tuple[str, ...]]:
    pkgs = rng.sample(_CRATES, min(n, len(_CRATES)))
    out = []
    for p in pkgs:
        v = f"{rng.randint(0, 9)}.{rng.randint(0, 40)}.{rng.randint(0, 9)}"
        frm = rng.choice(pkgs)
        out.append(
            f"Requirement already satisfied: {p}>={v.split('.', maxsplit=1)[0]}.0 in ./.venv/lib/python3.12/site-packages (from {frm}) ({v})"
        )
    bad = "ERROR: pip's dependency resolver does not currently take into account all the packages that are installed. This behaviour is the source of the following dependency conflicts.\nacme-shop 0.9.0 requires pydantic<3,>=2.13, but you have pydantic 2.9.2 which is incompatible."
    out.append(bad)
    out.append(f"Successfully installed acme-shop-0.9.0 {pkgs[0]}-1.2.3")
    return "\n".join(out) + "\n", ("pydantic<3,>=2.13", "pydantic 2.9.2")


def npm_install(rng: random.Random) -> tuple[str, tuple[str, ...]]:
    deprecated = (
        "inflight@1.0.6: This module is not supported, and leaks memory. Do not use it.",
        "glob@7.2.3: Glob versions prior to v9 are no longer supported",
        "rimraf@3.0.2: Rimraf versions prior to v4 are no longer supported",
        "@humanwhocodes/config-array@0.13.0: Use @eslint/config-array instead",
        "abab@2.0.6: Use your platform's native atob() and btoa() methods instead",
        "domexception@4.0.0: Use your platform's native DOMException instead",
        "w3c-hr-time@1.0.2: Use your platform's native performance.now() and performance.timeOrigin.",
        "stable@0.1.8: Modern JS already guarantees Array#sort() is a stable sort, so this library is deprecated.",
    )
    out = [f"npm warn deprecated {rng.choice(deprecated)}" for _ in range(rng.randint(14, 30))]
    out += [
        "npm warn ERESOLVE overriding peer dependency",
        "npm warn While resolving: @acme/web@0.9.0",
        "npm warn Found: react@19.2.0",
        "npm warn node_modules/react",
        'npm warn   react@"^19.2.0" from the root project',
        "",
        f"added {rng.randint(800, 1400)} packages, and audited {rng.randint(1400, 1600)} packages in {rng.randint(8, 50)}s",
        "",
        f"{rng.randint(150, 260)} packages are looking for funding",
        "  run `npm fund` for details",
        "",
        "3 vulnerabilities (1 moderate, 2 high)",
        "",
        "To address all issues, run:",
        "  npm audit fix",
    ]
    return "\n".join(out) + "\n", ("3 vulnerabilities (1 moderate, 2 high)",)


def ls_long(rng: random.Random, proj: _Project, n: int) -> tuple[str, tuple[str, ...]]:
    names = sorted({p.rsplit("/", 1)[-1] for p in proj.py_files + proj.ts_files})[:n]
    out = [f"total {rng.randint(200, 900)}"]
    out.append("drwxr-xr-x  14 dev dev   4096 Oct 14 18:20 .")
    out.append("drwxr-xr-x   6 dev dev   4096 Oct  2 09:11 ..")
    for nm in names:
        size = rng.randint(120, 40000)
        d = rng.randint(1, 14)
        out.append(
            f"-rw-r--r--   1 dev dev {size:>6} Oct {d:>2} {rng.randint(8, 22):02d}:{rng.randint(0, 59):02d} {nm}"
        )
    return "\n".join(out) + "\n", (names[len(names) // 2],)


def find_paths(rng: random.Random, proj: _Project, n: int) -> tuple[str, tuple[str, ...]]:
    paths = sorted(rng.sample(proj.py_files + proj.ts_files + proj.test_files, n))
    out = ["./" + p for p in paths]
    return "\n".join(out) + "\n", (out[n // 2],)


def tree(rng: random.Random, proj: _Project) -> tuple[str, tuple[str, ...]]:
    out = ["."]
    pkgs = list(_PY_PKGS)
    for pi, p in enumerate(pkgs):
        last_p = pi == len(pkgs) - 1
        out.append(f"{'└──' if last_p else '├──'} {p}")
        mods = rng.sample(_PY_MODS, rng.randint(4, len(_PY_MODS)))
        for mi, m in enumerate(mods):
            last_m = mi == len(mods) - 1
            out.append(f"{'    ' if last_p else '│   '}{'└──' if last_m else '├──'} {m}.py")
    out.append("")
    out.append(f"{len(pkgs)} directories, {len(out) - len(pkgs) - 2} files")
    return "\n".join(out) + "\n", ("billing",)


def kubectl_pods(rng: random.Random, n: int) -> tuple[str, tuple[str, ...]]:
    out = [f"{'NAMESPACE':<14}{'NAME':<48}{'READY':<8}{'STATUS':<20}{'RESTARTS':<14}AGE"]
    crash = ""
    for i in range(n):
        svc = rng.choice(("api", "web", "billing-worker", "search", "notify", "ledger"))
        name = f"{svc}-{hashlib.md5(str(rng.random()).encode()).hexdigest()[:10]}-{hashlib.md5(str(rng.random()).encode()).hexdigest()[:5]}"
        status, restarts = "Running", "0"
        if i == n // 2:
            status, restarts, crash = "CrashLoopBackOff", f"{rng.randint(5, 40)} (2m ago)", name
        out.append(
            f"{rng.choice(('prod', 'prod', 'staging')):<14}{name:<48}{'1/1' if status == 'Running' else '0/1':<8}{status:<20}{restarts:<14}{rng.randint(1, 30)}d"
        )
    return "\n".join(out) + "\n", (crash, "CrashLoopBackOff")


# ─── Structured results ──────────────────────────────────────────────────────


def github_pulls(rng: random.Random, proj: _Project, n: int) -> tuple[str, tuple[str, ...]]:
    """A GitHub REST list: every row unique, half of every row is URL boilerplate."""
    api = "https://api.github.com/repos/acme/acme-shop"
    rows = []
    for i in range(n):
        num = 2400 - i * rng.randint(1, 4)
        name, _ = proj.person()
        login = name.split()[0].lower() + str(rng.randint(1, 99))
        rows.append(
            {
                "url": f"{api}/pulls/{num}",
                "id": rng.randint(10**9, 3 * 10**9),
                "node_id": "PR_kwDO" + hashlib.sha1(str(num).encode()).hexdigest()[:14],
                "html_url": f"https://github.com/acme/acme-shop/pull/{num}",
                "diff_url": f"https://github.com/acme/acme-shop/pull/{num}.diff",
                "patch_url": f"https://github.com/acme/acme-shop/pull/{num}.patch",
                "issue_url": f"{api}/issues/{num}",
                "number": num,
                "state": rng.choice(("open", "open", "closed")),
                "locked": False,
                "title": f"{rng.choice(_PREFIXES)}: {rng.choice(_SUBJECTS)}",
                "user": {
                    "login": login,
                    "id": rng.randint(10**5, 10**8),
                    "avatar_url": f"https://avatars.githubusercontent.com/u/{rng.randint(10**5, 10**8)}?v=4",
                    "url": f"https://api.github.com/users/{login}",
                    "html_url": f"https://github.com/{login}",
                    "type": "User",
                    "site_admin": False,
                },
                "body": rng.choice(
                    (
                        None,
                        f"Fixes #{rng.randint(100, 2400)}. Tested locally against staging.",
                        f"## Summary\n\nThis {rng.choice(('fixes', 'reworks', 'speeds up'))} the {rng.choice(_NOUNS)} path.\n\n## Test plan\n\n- [x] unit tests\n- [ ] staging",
                    )
                ),
                "created_at": f"2026-{rng.randint(7, 10):02d}-{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00Z",
                "updated_at": f"2026-10-{rng.randint(1, 15):02d}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00Z",
                "merged_at": None,
                "draft": rng.random() < 0.2,
                "labels": [
                    {"name": lb, "color": "d73a4a"}
                    for lb in rng.sample(
                        ("bug", "backend", "frontend", "needs-review", "p1"), rng.randint(0, 2)
                    )
                ],
                "commits_url": f"{api}/pulls/{num}/commits",
                "review_comments_url": f"{api}/pulls/{num}/comments",
                "comments_url": f"{api}/issues/{num}/comments",
                "statuses_url": f"{api}/statuses/{proj.sha()}",
                "head": {"ref": f"feature/{rng.choice(_NOUNS)}-{num}", "sha": proj.sha()},
                "base": {"ref": "main", "sha": proj.sha()},
                "author_association": rng.choice(("MEMBER", "CONTRIBUTOR")),
            }
        )
    pick = rows[n // 3]
    text = json.dumps(rows, indent=2)
    return text, (str(pick["number"]), pick["title"], pick["user"]["login"])


def db_rows(rng: random.Random, n: int) -> tuple[str, tuple[str, ...]]:
    """A database MCP server's query result: unique ids, varied values."""
    rows = []
    for _ in range(n):
        rows.append(
            {
                "order_id": f"ord_{rng.randint(10**7, 10**8 - 1)}",
                "customer_id": f"cus_{rng.randint(10**5, 10**6 - 1)}",
                "status": rng.choice(("paid", "paid", "paid", "refunded", "pending", "failed")),
                "total_cents": rng.randint(499, 49999),
                "currency": rng.choice(("EUR", "EUR", "USD", "GBP")),
                "items": rng.randint(1, 9),
                "created_at": f"2026-10-{rng.randint(1, 15):02d}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z",
                "country": rng.choice(("DE", "FR", "US", "GB", "NL", "AT")),
            }
        )
    rows[n // 2]["status"] = "chargeback"
    pick = rows[n // 2]
    text = json.dumps(
        {
            "columns": list(rows[0]),
            "row_count": n,
            "rows": rows,
            "execution_time_ms": rng.randint(20, 400),
        }
    )
    return text, (pick["order_id"], "chargeback", str(pick["total_cents"]))


def linear_issues(rng: random.Random, proj: _Project, n: int) -> tuple[str, tuple[str, ...]]:
    """An issue-tracker MCP result (Linear/Jira-style), nested and chatty."""
    issues = []
    for i in range(n):
        name, email = proj.person()
        issues.append(
            {
                "id": hashlib.md5(str(rng.random()).encode()).hexdigest(),
                "identifier": f"SHOP-{1200 + i}",
                "title": rng.choice(_SUBJECTS).capitalize(),
                "priority": rng.choice((0, 1, 2, 2, 3, 3, 4)),
                "priorityLabel": None,
                "state": {
                    "name": rng.choice(("Todo", "In Progress", "In Review", "Backlog")),
                    "type": "unstarted",
                },
                "assignee": {"name": name, "email": email, "active": True},
                "team": {"key": "SHOP", "name": "Shop"},
                "labels": {
                    "nodes": [
                        {"name": lb}
                        for lb in rng.sample(
                            ("bug", "backend", "frontend", "infra", "customer"), rng.randint(0, 2)
                        )
                    ]
                },
                "estimate": rng.choice((None, 1, 2, 3, 5, 8)),
                "createdAt": f"2026-{rng.randint(6, 10):02d}-{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}:00:00.000Z",
                "url": f"https://linear.app/acme/issue/SHOP-{1200 + i}",
            }
        )
    issues[n // 4]["priority"] = 1
    issues[n // 4]["title"] = "Checkout charges EU customers twice when 3DS times out"
    pick = issues[n // 4]
    return json.dumps({"issues": {"nodes": issues, "pageInfo": {"hasNextPage": True}}}), (
        pick["identifier"],
        pick["title"],
    )


# ─── Pages, traces, prose ────────────────────────────────────────────────────


def web_page(rng: random.Random) -> tuple[str, tuple[str, ...]]:
    """What a WebFetch of a docs page looks like: nav, cookie banner, footer."""
    nav = [
        f"- [{t}](https://docs.payments.example/{t.lower().replace(' ', '-')})"
        for t in (
            "Overview",
            "Quickstart",
            "Payments",
            "Refunds",
            "Webhooks",
            "Idempotency",
            "Errors",
            "Testing",
            "API reference",
            "SDKs",
            "Changelog",
            "Status",
            "Support",
            "Pricing",
        )
    ]
    params = [
        ("amount", "integer", "required", "Amount in the smallest currency unit."),
        ("currency", "string", "required", "Three-letter ISO code, lowercase."),
        (
            "idempotency_key",
            "string",
            "optional",
            "Up to 255 characters. Keys expire after 24 hours.",
        ),
        ("capture_method", "string", "optional", "`automatic` (default) or `manual`."),
        ("metadata", "object", "optional", "Up to 50 keys, values up to 500 characters."),
        ("statement_descriptor", "string", "optional", "At most 22 characters."),
    ]
    out = [
        "Skip to content",
        "We use cookies to improve your experience. By continuing you accept our [Cookie Policy](https://docs.payments.example/legal/cookies). [Accept all](#) [Reject](#) [Settings](#)",
        "",
        *nav,
        "",
        "# Create a payment",
        "",
        "Last updated 2026-09-30 · 6 min read · [Edit this page](https://github.com/example/docs/edit/main/payments/create.md)",
        "",
        "Creates a payment and, unless `capture_method` is `manual`, captures it immediately.",
        "",
        "## Parameters",
        "",
        "| Name | Type | Required | Description |",
        "|---|---|---|---|",
        *[f"| `{a}` | {b} | {c} | {d} |" for a, b, c, d in params],
        "",
        "## Retries",
        "",
        "Retrying a request with the same idempotency key returns the original response for 24 hours. "
        "After that the key may be reused. A request that differs from the original but reuses its key "
        "fails with `409 idempotency_key_reused`.",
        "",
        "```bash",
        "curl https://api.payments.example/v3/payments \\",
        "  -u sk_test_xxx: \\",
        '  -H "Idempotency-Key: 8f14e45f" \\',
        "  -d amount=2000 -d currency=eur",
        "```",
        "",
        "Was this page helpful? [Yes](#) [No](#)",
        "",
        *[
            f"- [{t}](https://docs.payments.example/{t.lower()})"
            for t in (
                "Company",
                "Careers",
                "Blog",
                "Press",
                "Partners",
                "Privacy",
                "Terms",
                "Cookies",
                "Sitemap",
            )
        ],
        "© 2026 Example Payments, Inc. All rights reserved.",
    ]
    out[2:2] = [""] * rng.randint(0, 2)
    return "\n".join(out) + "\n", (
        "409 idempotency_key_reused",
        "24 hours",
        "At most 22 characters",
    )


def java_trace(rng: random.Random, frames: int) -> tuple[str, tuple[str, ...]]:
    spring = (
        "org.springframework.web.servlet.FrameworkServlet.processRequest(FrameworkServlet.java:1014)",
        "org.springframework.web.servlet.DispatcherServlet.doDispatch(DispatcherServlet.java:1089)",
        "org.springframework.web.method.support.InvocableHandlerMethod.invokeForRequest(InvocableHandlerMethod.java:150)",
        "org.apache.catalina.core.ApplicationFilterChain.doFilter(ApplicationFilterChain.java:138)",
        "org.springframework.web.filter.OncePerRequestFilter.doFilter(OncePerRequestFilter.java:116)",
        "org.apache.catalina.core.StandardWrapperValve.invoke(StandardWrapperValve.java:167)",
        "org.apache.coyote.http11.Http11Processor.service(Http11Processor.java:391)",
        "org.apache.tomcat.util.net.NioEndpoint$SocketProcessor.doRun(NioEndpoint.java:1736)",
        "java.base/java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1144)",
        "jdk.internal.reflect.DirectMethodHandleAccessor.invoke(DirectMethodHandleAccessor.java:103)",
    )
    line = rng.randint(40, 400)
    out = [
        f"2026-10-14 18:22:{rng.randint(0, 59):02d}.{rng.randint(0, 999):03d} ERROR 1 --- [nio-8080-exec-{rng.randint(1, 9)}] o.a.c.c.C.[.[.[/].[dispatcherServlet]    : Servlet.service() for servlet [dispatcherServlet] threw exception",
        "",
        "org.springframework.dao.DataIntegrityViolationException: could not execute statement; constraint [uk_payment_idempotency_key]",
        f"\tat com.acme.shop.billing.PaymentService.capture(PaymentService.java:{line})",
        f"\tat com.acme.shop.billing.PaymentController.capture(PaymentController.java:{rng.randint(30, 90)})",
    ]
    out += [f"\tat {rng.choice(spring)}" for _ in range(frames)]
    out += [
        'Caused by: org.postgresql.util.PSQLException: ERROR: duplicate key value violates unique constraint "uk_payment_idempotency_key"',
        "  Detail: Key (idempotency_key)=(8f14e45f) already exists.",
        "\tat org.postgresql.core.v3.QueryExecutorImpl.receiveErrorResponse(QueryExecutorImpl.java:2733)",
        *[f"\tat {rng.choice(spring)}" for _ in range(frames // 2)],
        f"\t... {rng.randint(40, 90)} common frames omitted",
    ]
    return "\n".join(out) + "\n", (
        f"PaymentService.java:{line}",
        "uk_payment_idempotency_key",
        "Key (idempotency_key)=(8f14e45f) already exists",
    )


def node_trace_in_log(rng: random.Random, lines: int) -> tuple[str, tuple[str, ...]]:
    out = []
    for i in range(lines):
        lvl = rng.choice(("info", "info", "info", "debug", "warn"))
        out.append(
            f'{{"level":"{lvl}","time":"2026-10-14T18:{i // 60:02d}:{i % 60:02d}.{rng.randint(0, 999):03d}Z","pid":{rng.randint(10, 99)},"msg":"{rng.choice(("request completed", "cache hit", "cache miss", "slow query", "job queued"))}","route":"/{rng.choice(_NOUNS)}s","ms":{rng.randint(1, 900)}}}'
        )
    at = rng.randint(lines // 3, 2 * lines // 3)
    trace = [
        "TypeError: Cannot read properties of undefined (reading 'currency')",
        "    at formatMoney (/app/web/src/utils/formatPrice.ts:14:37)",
        "    at CartDrawer (/app/web/src/components/CartDrawer.tsx:88:19)",
        "    at renderWithHooks (/app/node_modules/react-dom/cjs/react-dom-server.node.development.js:5662:16)",
        "    at renderElement (/app/node_modules/react-dom/cjs/react-dom-server.node.development.js:5938:15)",
        "    at retryNode (/app/node_modules/react-dom/cjs/react-dom-server.node.development.js:6390:7)",
    ]
    out[at:at] = trace
    return "\n".join(out) + "\n", (
        "Cannot read properties of undefined (reading 'currency')",
        "formatPrice.ts:14:37",
    )


_PROSE = (
    "The {n} service is the only writer of the {n}s table, and every other service reads through its API.",
    "We chose this because two writers raced during the March incident and produced duplicate {n}s.",
    "In practice that means a consumer that needs a {n} must call the service, even if a read replica is closer.",
    "It is worth noting that, generally speaking, this costs one additional network hop of roughly {ms} ms at p95.",
    "Retries are safe because every mutating endpoint accepts an idempotency key that is stored for {h} hours.",
    "As a matter of fact, most of the complexity in this design comes from the fact that refunds can arrive before captures.",
    "When that happens the refund is parked in a pending state and replayed by the reconciler every {m} minutes.",
    "We considered, and ultimately rejected, an event-sourced design, mainly because nobody on the team had operated one.",
    "The decision is revisited if the write volume exceeds {k} requests per second, which is about four times today's peak.",
    "Basically, in order to keep things simple, we deliberately avoid distributed transactions entirely.",
)


def prose_doc(rng: random.Random, paragraphs: int) -> tuple[str, tuple[str, ...]]:
    n = rng.choice(_NOUNS)
    vals = {
        "n": n,
        "ms": rng.randint(2, 9),
        "h": rng.choice((24, 48, 72)),
        "m": rng.choice((5, 10, 15)),
        "k": rng.choice((800, 1200, 2000)),
    }
    out = [f"# ADR-{rng.randint(10, 60)}: {n.title()} ownership", "", "Status: accepted", ""]
    for p in range(paragraphs):
        out.append(
            f"## {('Context', 'Decision', 'Consequences', 'Alternatives', 'Operations', 'Open questions')[p % 6]}"
        )
        out.append("")
        out.append(" ".join(s.format(**vals) for s in rng.sample(_PROSE, rng.randint(3, 6))))
        out.append("")
    return "\n".join(out), (f"{vals['h']} hours", f"{vals['k']} requests per second")


def read_view(text: str) -> str:
    """Claude Code's Read tool: `cat -n`-style numbers and an arrow."""
    return "\n".join(f"{i:>6}→{line}" for i, line in enumerate(text.split("\n")[:-1], 1)) + "\n"


def package_json(rng: random.Random) -> str:
    deps = {
        c: f"^{rng.randint(1, 9)}.{rng.randint(0, 30)}.{rng.randint(0, 9)}"
        for c in rng.sample(_CRATES, 14)
    }
    return (
        json.dumps(
            {
                "name": "@acme/web",
                "version": "0.9.0",
                "private": True,
                "type": "module",
                "scripts": {
                    "dev": "vite",
                    "build": "tsc -b && vite build",
                    "test": "vitest run",
                    "lint": "eslint .",
                },
                "dependencies": deps,
                "devDependencies": {"typescript": "^5.9.3", "vite": "^8.1.0", "vitest": "^4.1.2"},
            },
            indent=2,
        )
        + "\n"
    )


# ─── Headroom-comparable scenarios ───────────────────────────────────────────
# Same tool shapes and sizes as Headroom's published proof table; own code.

_REPOS = [
    "facebook/react",
    "microsoft/vscode",
    "tensorflow/tensorflow",
    "kubernetes/kubernetes",
    "golang/go",
    "rust-lang/rust",
    "apache/spark",
    "elastic/elasticsearch",
    "grafana/grafana",
    "prometheus/prometheus",
    "docker/cli",
    "nginx/nginx",
]


def hr_code_search(rng: random.Random, query: str, n: int) -> dict:
    slug = query.lower().replace(" ", "_")
    items = []
    for i in range(n):
        repo = rng.choice(_REPOS)
        items.append(
            {
                "repository": {
                    "full_name": repo,
                    "description": f"The {repo.split('/')[1]} project",
                    "stars": rng.randint(1000, 100000),
                    "language": rng.choice(("Python", "Go", "TypeScript", "Java", "Rust")),
                    "updated_at": f"2026-09-{rng.randint(1, 28):02d}T00:00:00Z",
                },
                "path": f"src/{slug}/handler_{i}.py",
                "sha": hashlib.sha1(f"{repo}{i}{rng.random()}".encode()).hexdigest(),
                "url": f"https://github.com/{repo}/blob/main/src/{slug}/handler_{i}.py",
                "score": round(rng.uniform(10, 100), 2),
                "text_matches": [
                    {
                        "fragment": f"def {slug}(request):\n    # Implementation\n    return response",
                        "matches": [{"text": query, "indices": [4, 4 + len(query)]}],
                    }
                ],
            }
        )
    return {"total_count": n * 50, "incomplete_results": False, "items": items}


def hr_log_search(rng: random.Random, n: int) -> dict:
    services = (
        "api-gateway",
        "auth-service",
        "payment-service",
        "user-service",
        "notification-service",
    )
    entries = []
    for i in range(n):
        level = rng.choice(("INFO", "INFO", "INFO", "INFO", "WARN", "ERROR", "DEBUG"))
        svc = rng.choice(services)
        if level == "ERROR":
            msg = rng.choice(
                (
                    f"Connection refused to {svc}:8080 - ECONNREFUSED",
                    f"Timeout waiting for response from {svc} after 30000ms",
                    "Failed to process request: NullPointerException",
                    "Database connection pool exhausted",
                )
            )
        elif level == "WARN":
            msg = rng.choice(
                (
                    "High latency detected: 2500ms (threshold: 1000ms)",
                    "Memory usage at 85%",
                    f"Retry attempt 3/5 for {svc}",
                )
            )
        else:
            msg = rng.choice(
                (
                    "Request processed successfully",
                    "Health check passed",
                    f"Cache hit for key: user_session_{rng.randint(1000, 9999)}",
                )
            )
        entries.append(
            {
                "timestamp": f"2026-10-14T{10 + i // 60:02d}:{i % 60:02d}:00Z",
                "level": level,
                "service": svc,
                "message": msg,
                "trace_id": hashlib.md5(f"{i}{rng.random()}".encode()).hexdigest()[:16],
                "metadata": {
                    "host": f"pod-{svc}-{rng.randint(1, 5)}",
                    "region": rng.choice(("us-east-1", "us-west-2", "eu-west-1")),
                },
            }
        )
    # The one line the incident is about.
    entries[n // 2] = {
        **entries[n // 2],
        "level": "ERROR",
        "service": "payment-service",
        "message": "Database connection pool exhausted (max=50, waiting=212)",
    }
    return {"total_hits": n * 10, "returned": n, "entries": entries}


def hr_db_rows(rng: random.Random, n: int) -> dict:
    rows = [
        {
            "user_id": f"user_{10000 + i}",
            "email": f"user{10000 + i}@example.com",
            "created_at": f"2026-0{rng.randint(1, 9)}-{rng.randint(1, 28):02d}",
            "last_login": f"2026-10-{rng.randint(1, 14):02d}T{rng.randint(0, 23):02d}:00:00Z",
            "total_orders": rng.randint(0, 100),
            "total_revenue": round(rng.uniform(0, 10000), 2),
            "status": rng.choice(("active", "active", "active", "inactive", "suspended")),
            "country": rng.choice(("US", "UK", "DE", "FR", "JP", "AU", "CA")),
            "subscription_tier": rng.choice(("free", "free", "basic", "premium", "enterprise")),
        }
        for i in range(n)
    ]
    rows[n // 3]["total_revenue"] = 98234.17
    return {
        "columns": list(rows[0]),
        "row_count": n,
        "rows": rows,
        "execution_time_ms": rng.randint(50, 500),
    }


def hr_file_search(rng: random.Random, query: str, n: int) -> dict:
    base = [
        "src/auth/jwt_handler.py",
        "src/auth/oauth_provider.py",
        "src/api/routes/users.py",
        "src/services/payment_processor.py",
        "src/middleware/rate_limiter.py",
        "src/middleware/auth_middleware.py",
        "src/models/user.py",
        "tests/test_auth.py",
        "config/settings.py",
    ]
    slug = query.lower().replace(" ", "_")
    matches = [
        {
            "path": base[i] if i < len(base) else f"src/modules/module_{i}.py",
            "type": "file",
            "size": rng.randint(500, 15000),
            "modified": f"2026-09-{rng.randint(1, 28):02d}",
            "matches": [
                {
                    "line": rng.randint(10, 500),
                    "content": f"    def process_{slug}(self, data):",
                    "context_before": "    # Process incoming request",
                    "context_after": f"        return self.handler.{slug}(data)",
                }
            ],
            "score": round(rng.uniform(0.5, 1.0), 3),
        }
        for i in range(n)
    ]
    return {"total_matches": n, "files_searched": n * 10, "matches": matches}


def hr_fs_tree(rng: random.Random, depth: int, files: int) -> dict:
    names = (
        "src",
        "lib",
        "utils",
        "components",
        "services",
        "models",
        "middleware",
        "tests",
        "config",
        "api",
        "core",
    )

    def walk(path: str, d: int) -> list:
        if d <= 0:
            return []
        entries = []
        for i in range(rng.randint(2, 4) if d > 1 else 0):
            nm = rng.choice(names) + (f"_{i}" if i else "")
            entries.append(
                {
                    "name": nm,
                    "type": "directory",
                    "path": f"{path}/{nm}",
                    "children": walk(f"{path}/{nm}", d - 1),
                }
            )
        for i in range(files):
            ext = rng.choice((".py", ".ts", ".js", ".json", ".yaml", ".md"))
            entries.append(
                {
                    "name": f"module_{i}{ext}",
                    "type": "file",
                    "path": f"{path}/module_{i}{ext}",
                    "size": rng.randint(100, 10000),
                    "modified": f"2026-09-{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00Z",
                }
            )
        return entries

    return {
        "name": "project",
        "type": "directory",
        "path": "/project",
        "children": walk("/project", depth),
    }


def hr_issues(rng: random.Random, n: int) -> dict:
    items = []
    for i in range(n):
        items.append(
            {
                "number": 1000 + i,
                "title": f"Issue #{1000 + i}: "
                + rng.choice(
                    (
                        "Fix authentication flow",
                        "Add support for OAuth2",
                        "Performance regression in v2.0",
                        "Documentation needs update",
                        "Memory leak in worker process",
                        "API rate limiting not working",
                    )
                ),
                "state": rng.choice(("open", "open", "open", "closed")),
                "user": {
                    "login": f"user{rng.randint(1, 1000)}",
                    "avatar_url": f"https://avatars.githubusercontent.com/u/{rng.randint(1, 100000)}",
                },
                "labels": rng.sample(
                    ("bug", "enhancement", "documentation", "help wanted", "good first issue"),
                    rng.randint(0, 3),
                ),
                "created_at": f"2026-09-{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}:00:00Z",
                "comments": rng.randint(0, 50),
                "body": "## Description\n\nThis issue tracks a bug.\n\n## Steps to Reproduce\n\n1. Step one\n2. Step two\n\n## Expected Behavior\n\nIt should work.",
            }
        )
    items[n // 2]["title"] = (
        f"Issue #{1000 + n // 2}: Data loss when two workers flush the same queue"
    )
    items[n // 2]["labels"] = ["bug", "p0"]
    return {"total_count": n, "items": items}


def _headroom_scenarios(rng: random.Random) -> list[Sample]:
    def s(scen: str, tool: str, obj: dict, facts: tuple[str, ...]) -> Sample:
        return Sample(
            name=f"{scen}:{tool}",
            kind="json_api",
            group=f"headroom:{scen}",
            tool="mcp",
            # Compact JSON, as Headroom's own harness feeds it.
            text=json.dumps(obj),
            facts=facts,
        )

    out: list[Sample] = []
    cs = hr_code_search(rng, "JWT authentication middleware", 100)
    out.append(
        s(
            "code_search",
            "github_search_code",
            cs,
            (cs["items"][37]["sha"], cs["items"][37]["repository"]["full_name"]),
        )
    )
    logs = hr_log_search(rng, 300)
    out.append(
        s(
            "sre_incident",
            "search_logs",
            logs,
            ("Database connection pool exhausted (max=50, waiting=212)",),
        )
    )
    out.append(s("sre_incident", "database_query", hr_db_rows(rng, 200), ("98234.17",)))
    fsr = hr_file_search(rng, "payment", 150)
    out.append(s("sre_incident", "search_files", fsr, ("src/services/payment_processor.py",)))
    fst = hr_fs_tree(rng, 3, 20)
    out.append(s("codebase_exploration", "filesystem_tree", fst, (fst["children"][0]["path"],)))
    fsa = hr_file_search(rng, "authentication", 200)
    out.append(
        s("codebase_exploration", "search_files", fsa, ("src/middleware/auth_middleware.py",))
    )
    cs2 = hr_code_search(rng, "JWT authentication middleware", 100)
    out.append(s("codebase_exploration", "github_search_code", cs2, (cs2["items"][5]["path"],)))
    iss = hr_issues(rng, 100)
    out.append(
        s(
            "issue_triage",
            "github_list_issues",
            iss,
            ("Data loss when two workers flush the same queue", "p0"),
        )
    )
    cs3 = hr_code_search(rng, "bug fix", 80)
    out.append(s("issue_triage", "github_search_code", cs3, (cs3["items"][11]["sha"],)))
    out.append(
        s(
            "issue_triage",
            "search_logs",
            hr_log_search(rng, 200),
            ("Database connection pool exhausted (max=50, waiting=212)",),
        )
    )
    return out


HEADROOM_SCENARIOS = {
    "code_search": "Code search (100 results)",
    "sre_incident": "SRE incident debugging",
    "codebase_exploration": "Codebase exploration",
    "issue_triage": "GitHub issue triage",
}

#: Headroom's own published figures for those scenarios (docs "Proof" table,
#: full-corpus config), quoted for context only — the head-to-head numbers come
#: from running both tools here.
HEADROOM_PUBLISHED = {
    "code_search": 21,
    "sre_incident": 57,
    "codebase_exploration": 42,
    "issue_triage": 30,
    "total": 41,
}


# ─── Assembly ────────────────────────────────────────────────────────────────


def build_corpus(seed: int = DEFAULT_SEED) -> list[Sample]:
    """The whole corpus, deterministically. Order matters: one RNG feeds all."""
    rng = random.Random(seed)
    proj = _Project(rng)
    out: list[Sample] = []

    def add(kind: str, tool: str, name: str, made: tuple[str, tuple[str, ...]], **kw) -> None:
        text, facts = made
        out.append(
            Sample(
                name=f"{kind}:{name}",
                kind=kind,
                group="agent",
                tool=tool,
                text=text,
                facts=facts,
                **kw,
            )
        )

    add("grep", "Bash", "grep -rn (60 hits)", grep_output(rng, proj, 60))
    add("grep", "Bash", "grep -rn (250 hits)", grep_output(rng, proj, 250))
    add("grep", "Grep", "rg -C2 --heading", rg_context(rng, proj, 8))
    add("git_log", "Bash", "git log -n 40", git_log(rng, proj, 40, stat=False))
    add("git_log", "Bash", "git log --stat -n 25", git_log(rng, proj, 25, stat=True))
    add("git_diff", "Bash", "git diff (3 files)", git_diff(rng, proj, 3, lockfile=False))
    add("git_diff", "Bash", "git diff (with lockfile)", git_diff(rng, proj, 2, lockfile=True))
    add("git_status", "Bash", "git status", git_status(rng, proj, 18))
    add("test_pytest", "Bash", "pytest -q (1 failure)", pytest_output(rng, proj, verbose=False))
    add("test_pytest", "Bash", "pytest -v (1 failure)", pytest_output(rng, proj, verbose=True))
    add("test_js", "Bash", "vitest run (1 failure)", vitest_output(rng, proj))
    add("build_cargo", "Bash", "cargo build (E0308)", cargo_build(rng))
    add("build_ci", "Bash", "GitHub Actions log", ci_log(rng, proj, 14))
    add("pkg_install", "Bash", "pip install", pip_install(rng, proj, 50))
    add("pkg_install", "Bash", "npm install", npm_install(rng))
    add("listing", "Bash", "ls -la", ls_long(rng, proj, 70))
    add("listing", "Bash", "find -name", find_paths(rng, proj, 150))
    add("listing", "Bash", "tree", tree(rng, proj))
    add("kubectl", "Bash", "kubectl get pods -A", kubectl_pods(rng, 60))
    add("json_api", "Bash", "gh api pulls (30)", github_pulls(rng, proj, 30))
    add("mcp", "mcp", "postgres query (150 rows)", db_rows(rng, 150))
    add("mcp", "mcp", "linear search (40 issues)", linear_issues(rng, proj, 40))
    add("web_page", "WebFetch", "docs page", web_page(rng))
    add("stack_trace", "Bash", "spring boot exception", java_trace(rng, 40))
    add("stack_trace", "Bash", "node trace in JSON log", node_trace_in_log(rng, 120))
    add("prose", "Read", "ADR markdown", prose_doc(rng, 6))

    # File reads: the model edits these next, so they must arrive unchanged.
    for _ in range(3):
        path = rng.choice(proj.py_files)
        src = python_module(rng, proj, path, rng.randint(6, 14))
        add(
            "file_read",
            "Read",
            f"Read {path}",
            (read_view(src), (src.split("\n")[3].strip(),)),
            byte_exact=True,
        )
    ts = rng.choice([f for f in proj.ts_files if f.endswith(".tsx")])
    tsrc = ts_module(rng, ts.rsplit("/", 1)[-1].split(".")[0])
    add("file_read", "Read", f"Read {ts}", (read_view(tsrc), ("useEffect",)), byte_exact=True)
    cpath = rng.choice(proj.py_files)
    add(
        "cat_source",
        "Bash",
        f"cat {cpath}",
        (python_module(rng, proj, cpath, 8), ("class ",)),
        byte_exact=True,
    )
    add(
        "cat_source",
        "Bash",
        "cat web/package.json",
        (package_json(rng), ('"vitest"',)),
        byte_exact=True,
    )

    out += _headroom_scenarios(rng)
    return [_with_question(s) for s in out]


# Questions for the optional model-in-the-loop check (quality_eval --model):
# each answer is one of the sample's facts, so it is checkable by substring.
_QUESTIONS = {
    "grep:grep -rn (60 hits)": lambda f: (f"Where is `{f[1]}` defined? Answer as path:line.", f[0]),
    "git_log:git log -n 40": lambda f: (f"What is the full hash of the commit '{f[1]}'?", f[0]),
    "test_pytest:pytest -q (1 failure)": lambda f: (
        "Which test failed? Answer with its pytest node id.",
        f[0],
    ),
    "build_cargo:cargo build (E0308)": lambda f: (
        "Which file:line:column does the compiler error point at?",
        f[1],
    ),
    "build_ci:GitHub Actions log": lambda f: (
        "Which file and line does mypy report? Answer path:line.",
        f[0],
    ),
    "json_api:gh api pulls (30)": lambda f: (
        f"Who opened pull request #{f[0]}? Answer with the login.",
        f[2],
    ),
    "mcp:postgres query (150 rows)": lambda f: ("Which order_id has status chargeback?", f[0]),
    "mcp:linear search (40 issues)": lambda f: (
        "Which issue identifier is about EU customers being charged twice?",
        f[0],
    ),
    "stack_trace:spring boot exception": lambda f: (
        "Where in the application code was the exception thrown? Answer File.java:line.",
        f[0],
    ),
    "kubectl:kubectl get pods -A": lambda f: (
        "Which pod is in CrashLoopBackOff? Answer with its full name.",
        f[0],
    ),
    "web_page:docs page": lambda f: (
        "Which error does reusing an idempotency key for a different request return?",
        f[0],
    ),
    "sre_incident:search_logs": lambda f: (
        "What exactly did payment-service log when its database pool ran out?",
        f[0],
    ),
}


def _with_question(s: Sample) -> Sample:
    make = _QUESTIONS.get(s.name)
    if not make:
        return s
    question, answer = make(s.facts)
    return replace(s, question=question, answer=answer)


def corpus_digest(samples: list[Sample]) -> str:
    """sha256 over every sample — two machines agree on this or the seed lied."""
    h = hashlib.sha256()
    for s in samples:
        h.update(s.name.encode())
        h.update(b"\0")
        h.update(s.text.encode())
        h.update(b"\0")
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--dump", metavar="DIR", help="write each sample to DIR for inspection")
    args = parser.parse_args()
    samples = build_corpus(args.seed)
    for s in samples:
        print(
            f"{s.group:<32}{s.name:<46}{len(s.text):>8} chars{'  byte-exact' if s.byte_exact else ''}"
        )
    print(f"\n{len(samples)} samples · seed {args.seed} · sha256 {corpus_digest(samples)[:16]}…")
    if args.dump:
        d = Path(args.dump)
        d.mkdir(parents=True, exist_ok=True)
        for i, s in enumerate(samples):
            safe = "".join(c if c.isalnum() else "_" for c in s.name)[:60]
            (d / f"{i:02d}_{safe}.txt").write_text(s.text, encoding="utf-8")
        print(f"wrote {len(samples)} files to {d}")


if __name__ == "__main__":
    main()
