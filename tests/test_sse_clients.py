"""Tests for SSE MCP client wrappers — behaviors 1-5."""
import re
import socket
import threading
import time

import pytest


# ---------------------------------------------------------------------------
# Behavior 1: disallowed tool raises PermissionError before any network call
# ---------------------------------------------------------------------------

def test_disallowed_tool_raises_permission_error():
    from agent.mcp_clients.sse_client import SseMcpClient
    client = SseMcpClient(url="http://127.0.0.1:19999/sse", read_only_tools=["ping"])
    with pytest.raises(PermissionError):
        client.call_tool("write_note", {})


# ---------------------------------------------------------------------------
# Behavior: list_tools() before connect() raises RuntimeError
# ---------------------------------------------------------------------------

def test_list_tools_before_connect_raises_runtime_error():
    from agent.mcp_clients.sse_client import SseMcpClient
    client = SseMcpClient(url="http://127.0.0.1:19999/sse", read_only_tools=["ping"])
    with pytest.raises(RuntimeError):
        client.list_tools()


# ---------------------------------------------------------------------------
# Behavior 2: unreachable URL raises ConnectionError containing the URL
# ---------------------------------------------------------------------------

def test_connect_to_unreachable_url_raises_connection_error_with_url():
    from agent.mcp_clients.sse_client import SseMcpClient
    url = "http://127.0.0.1:19999/sse"
    client = SseMcpClient(url=url, read_only_tools=["ping"])
    with pytest.raises(ConnectionError, match=re.escape(url)):
        client.connect()


# ---------------------------------------------------------------------------
# Behavior 3: KnowledgeGraphClient blocks known write tools
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("write_tool", [
    "stage_note",
    "approve_staged_note",
    "commit_approved_notes",
])
def test_knowledge_graph_client_blocks_write_tools(write_tool):
    from agent.mcp_clients.knowledge_graph import KnowledgeGraphClient
    client = KnowledgeGraphClient(url="http://127.0.0.1:19999/sse")
    with pytest.raises(PermissionError):
        client.call_tool(write_tool, {})


# ---------------------------------------------------------------------------
# Behavior 4: all four concrete wrappers importable with non-empty allowlists
# ---------------------------------------------------------------------------

def test_all_concrete_wrappers_have_non_empty_allowlists():
    from agent.mcp_clients.knowledge_graph import KnowledgeGraphClient
    from agent.mcp_clients.code_graph import CodeGraphClient
    from agent.mcp_clients.oracle import OracleClient
    from agent.mcp_clients.azure_devops import AzureDevOpsClient

    for Client in (KnowledgeGraphClient, CodeGraphClient, OracleClient, AzureDevOpsClient):
        assert len(Client.ALLOWED_TOOLS) > 0, f"{Client.__name__}.ALLOWED_TOOLS must not be empty"


# ---------------------------------------------------------------------------
# Behavior 5: allowed tool call returns a string (in-process FastMCP SSE server)
# ---------------------------------------------------------------------------

def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mcp_sse_server():
    """Spin up a minimal FastMCP SSE server in a background thread.

    Yields the base URL (``http://127.0.0.1:<port>``).
    """
    import uvicorn
    from mcp.server.fastmcp import FastMCP

    mcp_app = FastMCP("test-server")

    @mcp_app.tool()
    def ping() -> str:
        """Return a fixed string."""
        return "pong"

    @mcp_app.tool()
    def write_note(text: str) -> str:
        """A write tool that must never be selectable by a read-only client."""
        return "saved"

    port = _find_free_port()

    # Try different ASGI app extraction methods across mcp SDK versions
    asgi_app = None
    for method_name in ("get_asgi_app", "sse_app", "asgi_app"):
        method = getattr(mcp_app, method_name, None)
        if callable(method):
            asgi_app = method()
            break
    if asgi_app is None:
        asgi_app = mcp_app

    config = uvicorn.Config(asgi_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    def _run_server():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(server.serve())
        finally:
            loop.close()

    t = threading.Thread(target=_run_server, daemon=True)
    t.start()

    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)
    else:
        pytest.fail("In-process MCP SSE server did not start within 5 seconds")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    t.join(timeout=3)


def test_allowed_tool_call_returns_string(mcp_sse_server):
    from agent.mcp_clients.sse_client import SseMcpClient
    url = f"{mcp_sse_server}/sse"
    with SseMcpClient(url=url, read_only_tools=["ping"]) as client:
        result = client.call_tool("ping", {})
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Behavior: list_tools() filters the server's real tool list to the allowlist
# ---------------------------------------------------------------------------

def test_list_tools_filters_to_allowlist(mcp_sse_server):
    from agent.mcp_clients.sse_client import SseMcpClient
    url = f"{mcp_sse_server}/sse"
    # Server exposes both "ping" and "write_note"; only "ping" is allowlisted.
    with SseMcpClient(url=url, read_only_tools=["ping"]) as client:
        tools = client.list_tools()
    names = [t["name"] for t in tools]
    assert names == ["ping"]
    assert "inputSchema" in tools[0]
