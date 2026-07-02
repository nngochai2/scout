"""CodeGraphClient — read-only wrapper for the NAA Code Graph MCP server."""
from agent.mcp_clients.sse_client import SseMcpClient


class CodeGraphClient(SseMcpClient):
    """Read-only SSE client for the NAA Code Graph MCP server.

    Which tools are callable is discovered at connect() time from the
    server's own ToolAnnotations.readOnlyHint — see SseMcpClient.
    """
