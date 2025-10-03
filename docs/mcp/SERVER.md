# Sumigaseyana MCP Server (stdio)

A minimal MCP-compatible stdio server exposing tools: chat, search, ingest.
It uses LSP-style `Content-Length` framing and JSON-RPC 2.0 methods:

- `initialize` → returns `protocolVersion`, `capabilities`, `serverInfo`
- `tools/list` → lists tools with `inputSchema`
- `tools/call` → executes a tool and returns `{ content: [{ type: "text", text: "<json>" }] }`

Run:

```
python app/mcp/server.py
```

Environment:
- `YANA_SERVER_VERSION` (default `1.0.0`)
- `YANA_POLICY_VERSION` (default `say-2025-09-23`)
- OpenAI-compatible env for LLM calls: `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`, etc.

Schemas:
- See `docs/mcp/*.schema.json` — parameters mirror HTTP `/v1` API.

Notes:
- The server currently returns tool results as a single text part containing JSON.
  Clients should parse the `text` field as JSON to access structured fields.
- The `ingest` tool accepts a local file path for `image`.

