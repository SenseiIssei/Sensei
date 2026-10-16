# Codex (CLI, IDE extension, desktop app)

All three surfaces share `~/.codex/config.toml` (or `$CODEX_HOME/config.toml`).
By default, `sensei connect` adds two tables to it:

```toml
[mcp_servers.sensei]
command = "sensei"
args = ["mcp"]

[model_providers.sensei]
name = "Sensei"
base_url = "http://127.0.0.1:7000/v1"
wire_api = "responses"
env_key = "OPENAI_API_KEY"
```

- **`[mcp_servers.sensei]`** works on every account, including a ChatGPT
  subscription.
- **`[model_providers.sensei]`** is only used if you choose it. API-key users
  can do so with `codex -c model_provider=sensei`.

## Surviving the Codex app

The Codex desktop app rewrites `config.toml` in its own order and does not
promise to keep comments. So Sensei never depends on marker comments: it finds
its tables by name, updates them in place, and undo removes them by name. Your
own tables, plugins and settings stay exactly where they are. Blocks written by
Sensei 0.2 between `# >>> sensei >>>` markers are migrated automatically.

## Opt-in: routing

```bash
sensei setup-tools --only codex --route
```

This sets the top-level `openai_base_url = "http://127.0.0.1:7000/v1"`. Sensei
inserts it before the first table, because a top-level key appended at the end
of the file would land inside the last table. The setting reroutes Codex's
built-in provider for **both** sign-in modes.

> **Note:** with a **ChatGPT sign-in**, Codex then sends ChatGPT tokens to
> Sensei. This only works with a Sensei gateway that forwards those tokens to
> `https://chatgpt.com/backend-api/codex`. Until that ships, use `--route` with
> API-key sign-in only.

For a single run, there is no need to edit any file:

```bash
sensei wrap codex          # = codex -c openai_base_url="http://localhost:7000/v1"
```

Codex ignores the `OPENAI_BASE_URL` environment variable, which is why Sensei
passes the setting with `-c` instead.

## Hooks

Codex hooks cannot replace tool output. `updatedMCPToolOutput` is parsed but
not supported, so Codex gets no compression hook.
