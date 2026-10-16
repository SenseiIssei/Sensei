# How Sensei's numbers are measured

Every number in the README's [How much smaller?](../README.md#how-much-smaller)
section comes from a file in `backend/benchmarks/results/`. A script writes those
files, renders the graphics and rewrites the table, and nightly CI fails when the
committed numbers stop matching what the code does. This page says what is
measured, how, and where the measurement could mislead.

## Re-running everything

From `backend/`, with Sensei installed (`pip install -e .`):

```bash
python -m benchmarks.headroom_env          # once: Headroom in ~/.cache/sensei-bench, pinned
python -m benchmarks.refresh --sessions    # measure (corpus, your sessions, gateway replay), redraw, rewrite the table
```

That's the whole procedure. Leave out `--sessions` to skip replaying your own
transcripts, and leave out `headroom_env` to measure Sensei alone. Headroom's last
numbers are kept as long as the corpus is byte-identical, because they depend on
nothing else. Other modes:

| Command | What it does |
|---|---|
| `python -m benchmarks.refresh --render-only` | Redraw graphics and table from the committed results, without measuring |
| `python -m benchmarks.refresh --check` | Exit 1 if the README or SVGs don't match the results (nightly runs this) |
| `python -m benchmarks.agent_bench --headroom` | Corpus head-to-head only, printed |
| `python -m benchmarks.agent_bench --check benchmarks/results/agent_corpus.json` | The nightly regression gate |
| `python -m benchmarks.session_replay --headroom` | Your sessions through both tools, printed |
| `python -m benchmarks.corpus --dump DIR` | Write every corpus sample to `DIR` to read it |
| `python benchmarks/quality_eval.py` | Fact retention on both corpora |

## What is measured

**One tokenizer, one denominator.** Both "before" and "after" are counted with
tiktoken `cl100k_base`, on the exact text the model would receive. Neither tool's
own token estimate is used. The denominator is the original tool output, and it is
the same for both tools.

**Sensei as the gateway runs it.** Each tool output goes through
`ContentRouter.compress(text, edit_target=True)`, the call `compress_anthropic_request`
makes for every `tool_result` block. Source code, line-numbered file views and JSON
*objects* stay byte-exact on this path, because the model edits them next by exact
string match.

**Headroom as it publishes itself.** Headroom runs in its own virtualenv. It is
never a dependency of this repository: `benchmarks/headroom_worker.py` runs under
Headroom's interpreter and talks JSON over a pipe. Each text arrives as the `tool`
message answering an assistant `tool_call`, with `CompressConfig(protect_recent=0)`.
That is the configuration Headroom's own proof table uses. Under its default (4),
a short conversation shields almost every tool result, so the measurement would be
of the guard rather than the compressor. The version is pinned in
`benchmarks/headroom_env.py`.

**Latency** is the compress call alone, after one warm-up call, repeated five times
per sample. It is reported as p50 and p95 over every call. Process start-up,
imports and model loading are excluded for both tools.

## The seeded agent corpus

`backend/benchmarks/corpus.py` generates the tool output of an everyday
coding-agent session for a fictional project:

- `grep`/`rg` results
- `git log`/`diff`/`status` (including a lockfile diff)
- `pytest`, `vitest` and `cargo` failures
- CI and docker build logs, and `pip`/`npm install` noise
- `ls`/`find`/`tree` and `kubectl` tables
- GitHub API lists and MCP results (database rows, issue trackers), every row unique
- WebFetch pages, Java and Node stack traces, and prose docs
- file reads in Claude Code's `Read` format and raw `cat` of source and `package.json`

Every sample carries the facts an agent would need out of it. File reads are marked
byte-exact.

It is synthetic on purpose: no transcript, no file from anyone's disk, no network.
The seed fixes every byte, and the corpus digest recorded next to each result
proves it. Change the seed and every number changes, so any figure quoted from it
must name the seed.

A second group rebuilds the four scenarios of
[Headroom's published proof table](https://github.com/headroomlabs-ai/headroom):

- code search with 100 results
- an SRE incident
- codebase exploration
- issue triage

The tool shapes and sizes match; the code is written from scratch here. As a
sanity check, Headroom on the rebuilt scenarios lands within a few points of the
figures it publishes for the originals.

## Your own sessions

`python -m benchmarks.session_replay` reads the sessions your agents already keep:

- `~/.claude/projects/**/*.jsonl` (Claude Code)
- `~/.codex/sessions/**/*.jsonl` (Codex)

It pushes every tool result through the same path the gateway uses. Identical
results are compressed once and counted every time they occur.

What it reports:

- tokens before and after, per tool and per command family (`git`, `test`,
  `search`, `Read`, `mcp` …);
- how much of the volume repeats an earlier result in the same session (the share
  cross-turn deduplication could remove);
- what the savings would have been worth against the usage each request actually
  recorded.

**Privacy.** Transcripts are read and never copied. Nothing is written unless you
pass `--summary-json`, and that file holds counts and token sums per category from
a fixed list: no text, no command lines, no paths, no project names. Sensei's own
warnings are silenced during a replay because they quote the payload they fire on.
The committed `results/session_replay.json` is such a file, from the maintainer's
machine. Re-running `refresh --sessions` replaces it with yours.

## Gateway replay

`session_replay` measures each tool result on its own. A real agent is billed per
*request*: the whole history is resent every turn, the provider serves the
unchanged prefix from its prompt cache, and anything that changes earlier bytes
is billed again as a cache write. `python -m benchmarks.gateway_replay` (written
with the cache-aware gateway, and run by `refresh --sessions`) measures that bill.

How it works:

- Every assistant turn in a Claude Code transcript becomes one Messages request,
  with Claude Code's cache breakpoints.
- Each request is sent through the gateway's real HTTP route, so the live zone,
  dedup, tool compaction and markers are all in play.
- Upstream is a stub that emulates Anthropic's prompt-cache accounting: prefix
  hashes at breakpoints, a 20-block lookback, a 5-minute TTL and a minimum prefix.
- The same requests are billed three ways: unmodified (`raw`), through 0.2's
  stateless compression, and through this gateway.

Effective cost is uncached input × 1 plus cache writes × 1.25 plus cache reads ×
0.1, in units of the input price. The README reports the gateway's change against
`raw`, together with the cache-hit rate. The sessions are an even spread across
sizes of the transcripts over 200 kB.

What it leaves out:

- Output tokens. A stub cannot know how the model would have answered.
- The real system prompt and tool list, which aren't in transcripts. A fixed-size
  synthetic prefix stands in for them.
- System-reminder attachments and subagent side-chains.

Nothing from the transcripts is written. `results/gateway_replay.json` holds
ratios, cache-hit rates, CPU per request and the number of sessions and turns,
with no token volumes.

## Cost model

`backend/benchmarks/cost.py` prices tokens the way a cached agent session is
billed:

- every request re-sends the whole conversation;
- what was sent before is a **cache read** (0.1× list price, 0.05× on the Claude 5.5
  family);
- what is new since the last request is a **cache write** (1.25×);
- output is billed separately and input compression does not change it.

A tool result of *n* tokens that enters at request *i* of a context segment of
*R* requests costs `n × price × (write + read × (R − i − 1))` until the next
compaction. That is what each saved token is worth.

Two results come from this model:

- **Real sessions:** the bill is the usage each request recorded (cache writes,
  cache reads, uncached input, output), priced at `claude-opus-5-5` list prices. The
  saving is computed per tool result from its position in its session.
- **Agent corpus:** the samples are put into one synthetic session: a 20k-token
  system prompt, one tool result per request, short answers. That session is billed
  twice, original and compressed. The shape is in `SessionShape` and is printed with
  the results.

Prices live in `cost.PRICES` with the date they were checked. The percentages hardly
depend on the price level, only on the ratio of input to output price and on the
cache multipliers.

**Known bias:** counts use cl100k. Claude's tokenizer counts code about 30% higher
on Claude 4.7+, so the dollar figure for real sessions errs low. The percentages
are ratios and are unaffected.

## Quality

Shrinking text and keeping its meaning are different claims.

**Facts.** Every corpus sample lists the strings an agent needs: the failing test's
node id, the commit hash, the `file:line:col` of a compiler error, the one pod in
`CrashLoopBackOff`. After compression each must still be literally present
(whitespace-insensitive, case-sensitive). The hand-written micro corpus is gated at
100%. On the agent corpus, losses are listed in the README, and nightly fails on any
*new* loss.

**Byte-exact file reads.** `Read` and `cat` output must come back unchanged, or the
model's next exact-match edit fails.

**Model in the loop (optional, off in CI).**

```bash
python benchmarks/quality_eval.py --model llama3.1 --base-url http://localhost:11434/v1
```

This asks each question twice, against the original and against the compressed
payload. A wrong answer counts against compression only when the original was
answered correctly. The `answers kept` figure is the one about compression rather
than the model. Point `--base-url` at the provider, not at a Sensei gateway,
otherwise the "original" arm is compressed too. It is not in CI because a gate
that needs a funded key gets switched off.

## Nightly

`.github/workflows/nightly.yml`:

- re-measures the corpus and runs `agent_bench --check` against the committed
  results. It fails when savings drop by more than one point, when a fact that used
  to survive is lost, or when a file read stops being byte-exact;
- runs `refresh --check`, so the README and SVGs can never disagree with the
  results they claim to show;
- runs the micro-corpus fact gate (100%) and the Rust/Python parity check;
- runs Headroom on the same corpus in a separate, informational job;
- appends the numbers to the [public trend](https://senseiissei.github.io/Sensei/).

A pull request that changes compression should re-run `refresh` and commit the
new results; the gate then holds the improvement.

## Limits

- The agent corpus is a model of agent traffic, not a sample of it. Its mix decides
  its aggregate; that's why the per-kind rows and the real-session row are shown
  next to it.
- The real-session row describes one person's sessions. Your mix of reads, shell
  output and MCP results decides yours, which is why the replay is one command.
- Per-result compression is one lever. Cross-turn deduplication, reversible clearing
  of stale results and tool-schema trimming act on the whole request, and the
  replay measures per tool result. The replay's "repeat" column already shows how
  much deduplication could remove; a request-level replay is needed to measure it
  once the gateway does it.
