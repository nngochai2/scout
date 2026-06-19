"""CodeGraphClient — read-only wrapper for the NAA Code Graph MCP server."""
from agent.mcp_clients.sse_client import SseMcpClient


class CodeGraphClient(SseMcpClient):
    """Read-only SSE client for the NAA Code Graph MCP server.

    Permits only query/read tools.  Write or mutation tools raise
    ``PermissionError`` without touching the network.
    """

    ALLOWED_TOOLS: list[str] = [
        "search_code",
        "get_file",
        "get_symbol",
        "get_references",
        "get_callers",
        "get_callees",
        "get_file_summary",
    ]

    def __init__(self, url: str) -> None:
        super().__init__(url=url, read_only_tools=self.ALLOWED_TOOLS)
