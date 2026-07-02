"""AzureDevOpsClient — read-only wrapper for the NAA Azure DevOps MCP server."""
from agent.mcp_clients.sse_client import SseMcpClient


class AzureDevOpsClient(SseMcpClient):
    """Read-only SSE client for the NAA Azure DevOps MCP server.

    Which tools are callable is discovered at connect() time from the
    server's own ToolAnnotations.readOnlyHint — see SseMcpClient.
    """
