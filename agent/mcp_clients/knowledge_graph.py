"""KnowledgeGraphClient — read-only wrapper for the NAA Knowledge Graph MCP server."""
from agent.mcp_clients.sse_client import SseMcpClient


class KnowledgeGraphClient(SseMcpClient):
    """Read-only SSE client for the NAA Knowledge Graph MCP server.

    Which tools are callable is discovered at connect() time from the
    server's own ToolAnnotations.readOnlyHint — write tools (stage_note,
    approve_staged_note, commit_approved_notes, etc.) are excluded there,
    not hardcoded here — see SseMcpClient.
    """
