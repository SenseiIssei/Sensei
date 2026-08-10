# Screenshots

## What's here

| File | What it shows |
|---|---|
| `savings.png` | The savings dashboard after routing five coding agents through the gateway. |
| `chat.png` | The chat window. |
| `mobile.png` | The UI at phone width with the sidebar drawer open. |

### How these were taken, and what is real in them

Worth writing down, because a screenshot is a claim about a product and it
should be possible to check it.

The traffic is real: 232 requests through the gateway carrying JSON API
responses, build logs and stack traces, sent with the User-Agent strings that
Claude Code, Cursor, Aider, Codex and Cline actually send — which is why the
"By tool" breakdown separates them. The compression figures are what the
pipeline produced on that content.

The output-shaping panel reads "no measurable difference", and that is the
honest result for this setup rather than a bug: the stub provider returns a
fixed reply regardless of the instruction, so there is no effect to find. It is
worth keeping in the screenshot — it shows what the panel does when the answer
is "nothing", which is the case a reader should see before they trust it in the
case where it says something.

Two things are not what a user would see in production:

- **The provider is a local stub** that returns `ok` to every call, because the
  point was to exercise the gateway rather than to spend money on 85 completions.
  Compression happens before the upstream call, so the savings are unaffected.
- **The history is a single day**, because the machine had been set up that
  morning. On a machine in daily use the thirty-day chart is the interesting
  part; here it is one bar.

Captured with Playwright at 1.5×/2× device scale, dark theme, viewport 1360×860
and 390×780.

## Still missing

| File | What it should show |
|---|---|
| `setup.png` | The first-run wizard — `sensei up` on a fresh install, before configuring anything. |

## Please

- **Redact your API keys.** They appear in the settings panel. Blur or crop
  them; a screenshot with a live key in it is a leaked key.
- **Use the dark theme** — it's the only one, so this is easy.
- Capture at 2× / retina if you can, then keep the file under ~400 kB.
- Real content beats lorem ipsum, but don't include anything private. A
  conversation about a public open-source repo works well.

## Adding them

Drop the files here and reference them in the README's "What it looks like"
section:

```markdown
<img src="docs/screenshots/setup.png" alt="Sensei's first-run setup screen" width="700">
```

Then open a PR. Replace the "Screenshots wanted" note in the README while you're
there.
