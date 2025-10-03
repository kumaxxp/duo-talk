# MCP Preparation for Sumigaseyana Integration

This folder contains JSON Schemas for MCP tools that mirror the HTTP v1 API.
The goal is to make the HTTP↔MCP mapping 1:1 so the Duo client can switch
from the HTTP provider to an MCP provider with minimal code changes.

## Tools

- chat: see `tools.chat.schema.json` (params/result)
- search: see `tools.search.schema.json` (params/result)
- ingest: see `tools.ingest.schema.json` (params/result)
- errors: common error object (see `errors.schema.json`)

## Mapping

- HTTP `/v1/chat` → MCP tool `chat`
- HTTP `/v1/search` → MCP tool `search`
- HTTP `/v1/ingest` → MCP tool `ingest`

The schemas are designed for JSON-RPC/MCP usage and only include the core
fields necessary for the Duo client. Additional fields can be added in a
non-breaking way.

## Versioning & Compatibility

- New fields are additive. Breaking changes require a new tool version name
  (e.g., `chat_v2`) or a different MCP namespace.
- Correlation fields `run_id`/`trace_id` can be passed via MCP context or as
  params; both patterns are acceptable.

