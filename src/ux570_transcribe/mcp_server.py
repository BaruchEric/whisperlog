"""MCP server exposing the transcript archive to Claude Desktop / Claude Code.

Tools:
- search_transcripts(query, limit) → snippets + recording IDs
- get_transcript(recording_id) → full text
- list_recent(limit) → timeline of recent recordings
- list_enrichments(recording_id) → past summaries / agent outputs

Run: `ux570-mcp` (stdio) — install the [mcp] extra first.
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
from .utils import setup_logging

logger = logging.getLogger("ux570.mcp")


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
    try:
        from mcp import types
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
    except ImportError as e:
        raise RuntimeError(
            "MCP SDK not installed. Install: `uv pip install -e '.[mcp]'`"
        ) from e

    server = Server("ux570-transcribe")

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
        if name == "search_transcripts":
            hits = search(arguments["query"], limit=int(arguments.get("limit", 10)))
            payload = [_hit_to_dict(h) for h in hits]
        elif name == "get_transcript":
            text = get_transcript_text(int(arguments["recording_id"]))
            payload = {"text": text}
        elif name == "list_recent":
            payload = _recent_to_dicts(limit=int(arguments.get("limit", 20)))
        elif name == "list_enrichments":
            payload = list_enrichments(int(arguments["recording_id"]))
        else:
            raise ValueError(f"Unknown tool: {name}")
        return [types.TextContent(type="text", text=json.dumps(payload, indent=2))]

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    setup_logging(verbose=False)
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
