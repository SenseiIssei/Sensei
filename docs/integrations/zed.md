# Zed

`sensei connect` registers Sensei as a context server (Zed's name for an MCP
server) in Zed's `settings.json`:

```json
{
  "context_servers": {
    "sensei": { "command": "sensei", "args": ["mcp"] }
  }
}
```

Zed's default settings file usually contains comments. Sensei will not rewrite
a file with comments, because doing so would delete them. In that case,
`sensei setup-tools` reports a manual step with exactly this snippet.

## Routing (manual)

Zed can send its own model traffic through Sensei with an OpenAI- or
Anthropic-compatible provider:

```json
{
  "language_models": {
    "anthropic_compatible": {
      "Sensei": { "api_url": "http://127.0.0.1:7000" }
    },
    "openai_compatible": {
      "Sensei": {
        "api_url": "http://127.0.0.1:7000/v1",
        "available_models": [{ "name": "gpt-5.1", "max_tokens": 200000 }]
      }
    }
  }
}
```

Zed reads the key for that provider from its keychain (or the provider's
environment variable). Sensei forwards that key upstream unchanged. Models
hosted by Zed itself cannot be routed.
