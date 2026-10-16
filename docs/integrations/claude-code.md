# Claude Code

By default, `sensei connect` sets up two things for Claude Code:

1. **A PostToolUse hook** in `~/.claude/settings.json`. After every `Bash`,
   `Grep`, `Glob`, `WebFetch`, `WebSearch` or MCP tool call, Claude Code POSTs
   the result to `http://127.0.0.1:7000/hooks/claude/post-tool-use`. Sensei
   answers with `updatedToolOutput`, a compressed version in the same shape.
2. **Sensei's MCP server**, registered at user scope in `~/.claude.json`, so
   the model can call `sensei_retrieve` for the exact original of anything
   that was compressed.

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash|Grep|Glob|WebFetch|WebSearch|mcp__.*",
        "hooks": [{ "type": "http", "url": "http://127.0.0.1:7000/hooks/claude/post-tool-use", "timeout": 15 }]
      }
    ]
  }
}
```

If `CLAUDE_CONFIG_DIR` is set, both files live in that directory instead:
`$CLAUDE_CONFIG_DIR/settings.json` and `$CLAUDE_CONFIG_DIR/.claude.json`.

## Why a hook and not `ANTHROPIC_BASE_URL`

- Claude Code (2.1.196 and later) turns **Remote Control** off while
  `ANTHROPIC_BASE_URL` points anywhere other than Anthropic.
- The desktop app's **Code tab** reads its gateway from its own configuration
  and ignores `ANTHROPIC_BASE_URL`.
- With the hook, Claude Code talks to Anthropic exactly as before, on your own
  sign-in. Only the tool output it is about to send is smaller.

## Never touched

- `Read`, `Edit`, `Write`, `NotebookEdit` and every other tool not in the
  matcher above. Edit matches `old_string` against what Read returned, so the
  model must see files byte for byte.
- Code inside a Bash or Grep result is kept byte-exact (`edit_target`).
- Outputs under 2,000 characters are left alone, and so are outputs that would
  shrink by less than 15%.
- Sensei's own MCP tools are never compressed: `sensei_retrieve` returns an
  original on purpose.

## Failing open

- If Sensei is not running, Claude Code logs a failed hook and uses the
  original output.
- If Sensei hits an error, it answers `{}` ("no change").
- Claude Code also checks the rewritten output against the tool's output schema
  and falls back to the original if it does not match. Sensei keeps every field
  and only replaces the text in it.

Savings are recorded in the ledger as **Claude Code (hook)**.

## Opt-in: routing through the gateway

```bash
sensei setup-tools --only claude-code --route
```

This sets `env.ANTHROPIC_BASE_URL` and adds a **SessionStart self-heal hook**
(`sensei hook claude-session-start`). At the start of each session, the hook
checks whether Sensei is answering:

- If it is not, the hook tries to start it.
- If Sensei still does not answer, the hook removes the base URL, so the next
  session talks to Anthropic directly instead of failing with
  "connection refused".

The background scan puts the base URL back the next time Sensei starts.

If the Claude Code VS Code extension's user settings exist, Sensei also sets
`claudeCode.environmentVariables` there. To undo all of this:

```bash
sensei setup-tools --only claude-code --no-route
```

The hook stays.

## Per repository

```bash
sensei setup-tools --project .
```

This writes the hook into `.claude/settings.local.json` (not the committed
`settings.json`) and the MCP server into `.mcp.json`.
