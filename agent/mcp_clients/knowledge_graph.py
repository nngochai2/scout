"""KnowledgeGraphClient — read-only wrapper for the NAA Knowledge Graph MCP server."""
from agent.mcp_clients.sse_client import SseMcpClient


class KnowledgeGraphClient(SseMcpClient):
    """Read-only SSE client for the NAA Knowledge Graph MCP server.

    Permits only the query/read tools exposed by the server.  Write tools
    (``stage_note``, ``approve_staged_note``, ``commit_approved_notes``, etc.)
    are intentionally excluded — calling them raises ``PermissionError``
    without touching the network.
    """

    ALLOWED_TOOLS: list[str] = [
        "search_notes",
        "get_note",
        "get_related_notes",
        "get_backlinks",
        "get_tagged_notes",
        "get_notes_by_type",
        "get_graph_stats",
    ]

    def __init__(self, url: str) -> None:
        super().__init__(url=url, read_only_tools=self.ALLOWED_TOOLS)
