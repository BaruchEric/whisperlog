"""MCP server exposing the transcript archive to Claude Desktop / Claude Code.

Tools:
- search_transcripts(query, limit) → snippets + recording IDs
- get_transcript(recording_id) → full text
- list_recent(limit) → timeline of recent recordings
- list_enrichments(recording_id) → past summaries / agent outputs

Run: `whisperlog-mcp` (stdio) — install the [mcp] extra first.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .archive import (
    SearchHit,
    get_transcript_text,
    list_enrichments,
    list_recordings,
    search,
)
from .utils import require_optional, setup_logging

logger = logging.getLogger(__name__)


def _hit_to_dict(h: SearchHit) -> dict[str, Any]:
    return {
        "recording_id": h.recording_id,
        "archive_path": str(h.archive_path),
        "md_path": str(h.md_path),
        "snippet": h.snippet,
        "rank": h.rank,
    }


def _recent_to_dicts(limit: int) -> list[dict[str, Any]]:
    return [
        {
            "recording_id": r.id,
            "archive_path": str(r.archive_path),
            "recorded_at": r.recorded_at,
            "ingested_at": r.ingested_at,
            "size_bytes": r.size_bytes,
            "duration_secs": r.duration_secs,
        }
        for r in list_recordings(limit=limit)
    ]


async def _serve() -> None:
    types = require_optional("mcp.types", "mcp")
    Server = require_optional("mcp.server", "mcp").Server
    stdio_server = require_optional("mcp.server.stdio", "mcp").stdio_server

    server = Server("whisperlog")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="search_transcripts",
                description="Full-text search across all transcripts. Returns ranked snippets.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "FTS5 query, e.g. 'sarah AND project'"},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="get_transcript",
                description="Fetch the full transcript text for a recording_id.",
                inputSchema={
                    "type": "object",
                    "properties": {"recording_id": {"type": "integer"}},
                    "required": ["recording_id"],
                },
            ),
            types.Tool(
                name="list_recent",
                description="List the most recent recordings.",
                inputSchema={
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "default": 20}},
                },
            ),
            types.Tool(
                name="list_enrichments",
                description="List prior summaries / agent outputs for a recording.",
                inputSchema={
                    "type": "object",
                    "properties": {"recording_id": {"type": "integer"}},
                    "required": ["recording_id"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        try:
            if name == "search_transcripts":
                hits = search(arguments["query"], limit=int(arguments.get("limit", 10)))
                payload: Any = [_hit_to_dict(h) for h in hits]
            elif name == "get_transcript":
                rid = int(arguments["recording_id"])
                text = get_transcript_text(rid)
                if text is None:
                    raise ValueError(f"recording {rid} not found")
                payload = {"text": text}
            elif name == "list_recent":
                payload = _recent_to_dicts(limit=int(arguments.get("limit", 20)))
            elif name == "list_enrichments":
                payload = list_enrichments(int(arguments["recording_id"]), with_text=False)
            else:
                raise ValueError(f"Unknown tool: {name}")
        except (KeyError, ValueError, TypeError) as e:
            return [types.TextContent(type="text", text=f"error: {e}")]
        return [types.TextContent(type="text", text=json.dumps(payload, indent=2))]

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    setup_logging(verbose=False)
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
