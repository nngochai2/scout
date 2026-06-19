"""AzureDevOpsClient — read-only wrapper for the NAA Azure DevOps MCP server."""
from agent.mcp_clients.sse_client import SseMcpClient


class AzureDevOpsClient(SseMcpClient):
    """Read-only SSE client for the NAA Azure DevOps MCP server.

    Permits only query/read tools.  Write or mutation tools (create_work_item,
    update_work_item, etc.) raise ``PermissionError`` without touching the network.
    """

    ALLOWED_TOOLS: list[str] = [
        "get_work_item",
        "list_work_items",
        "search_work_items",
        "get_pull_request",
        "list_pull_requests",
        "get_pipeline_run",
        "list_builds",
    ]

    def __init__(self, url: str) -> None:
        super().__init__(url=url, read_only_tools=self.ALLOWED_TOOLS)
