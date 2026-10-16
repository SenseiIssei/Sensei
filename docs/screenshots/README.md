# Screenshots

| File | What it shows |
|---|---|
| `overview-dark.png` | The landing screen after routing five coding agents through the gateway. |
| `overview-light.png` | The same, in the light theme. |
| `connections-dark.png` | Which AI tools on the machine are connected, and the gateway addresses. |
| `settings-light.png` | Theme, the chat's own model, updates, autostart. |
| `chat-light.png` | The chat on a machine with no provider configured: the first-run setup. |
| `mobile-dark.png` | The overview at phone width. |

## How these were taken, and what is real in them

A screenshot is a claim about a product, so it should be possible to check it.

**The traffic is real.** 70 requests went through the gateway carrying what
coding agents actually send as tool results — JSON API responses, build logs,
a compiler error, a disassembly listing, prose — under the User-Agent strings
of Claude Code, Codex (over the Responses API), Cursor, Aider and Cline. That is
why "By tool" separates them. The compression figures are what the pipeline
produced on that content.

**The provider is a local stub.** It answers every call with a short reply and a
usage block that reports a share of the prompt as prompt-cache reads, so the
cache panel has something to show without paying for 70 completions. Compression
happens before the upstream call, so the savings are unaffected; the cache hit
rate is the stub's, not a real provider's.

**The history is one day**, because the demo database was created that night.

**The tool list on the Connections page is the capturing machine's real one.**

## Reproducing them

Start Sensei with some traffic behind it, then:

```bash
cd frontend
node scripts/capture-screenshots.mjs http://localhost:7000/app/ ../docs/screenshots
```

Every view, dark and light, at 2× (the phone at 3×), with reduced motion so
nothing is caught mid-animation. Keep each file under ~400 kB, and never capture
a settings page with a real API key on it.
