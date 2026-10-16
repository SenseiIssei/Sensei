# JetBrains AI Assistant and Junie

## AI Assistant

AI Assistant keeps its model and MCP settings in the IDE's settings UI. Their
storage format is not documented, so Sensei cannot connect AI Assistant
automatically. There are two manual routes:

- **MCP:** Settings → Tools → AI Assistant → Model Context Protocol → **Import
  from Claude**. This imports the servers in Claude Desktop's config, and
  `sensei connect` writes Sensei's entry there.
- **Routing:** add a custom OpenAI-compatible model with the base URL
  `http://127.0.0.1:7000/v1` and your own provider key. Sensei forwards that
  key upstream unchanged.

## Junie

`sensei connect` adds Sensei to `~/.junie/mcp/mcp.json`, which the Junie CLI
and the IDE plugin share. For routing, create a custom model profile at
`~/.junie/models/sensei.json`:

```json
{
  "id": "sensei",
  "baseUrl": "http://127.0.0.1:7000/v1/chat/completions",
  "apiType": "OpenAICompletion"
}
```

Then select it with `junie --model custom:sensei`.
