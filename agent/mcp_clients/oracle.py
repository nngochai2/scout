"""OracleClient — read-only wrapper for the NAA Oracle MCP server."""
from agent.mcp_clients.sse_client import SseMcpClient


class OracleClient(SseMcpClient):
    """Read-only SSE client for the NAA Oracle MCP server.

    Permits only query/read tools.  Write or mutation tools raise
    ``PermissionError`` without touching the network.
    """

    ALLOWED_TOOLS: list[str] = [
        "query",
        "get_schema",
        "list_tables",
        "describe_table",
        "get_row_count",
    ]

    def __init__(self, url: str) -> None:
        super().__init__(url=url, read_only_tools=self.ALLOWED_TOOLS)
