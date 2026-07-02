"""Tests for SSE MCP client wrappers.

The allowlist is no longer a hand-maintained constant per client — it's
discovered at connect() time from the server's own declared
ToolAnnotations.readOnlyHint (see agent/mcp_clients/sse_client.py).
"""
import re
import socket
import threading
import time

import pytest


# ---------------------------------------------------------------------------
# Behavior: list_tools() before connect() raises RuntimeError
# ---------------------------------------------------------------------------

def test_list_tools_before_connect_raises_runtime_error():
    from agent.mcp_clients.sse_client import SseMcpClient
    client = SseMcpClient(url="http://127.0.0.1:19999/sse")
    with pytest.raises(RuntimeError):
        client.list_tools()


# ---------------------------------------------------------------------------
# Behavior: unreachable URL raises ConnectionError containing the URL
# ---------------------------------------------------------------------------

def test_connect_to_unreachable_url_raises_connection_error_with_url():
    from agent.mcp_clients.sse_client import SseMcpClient
    url = "http://127.0.0.1:19999/sse"
    client = SseMcpClient(url=url)
    with pytest.raises(ConnectionError, match=re.escape(url)):
        client.connect()


# ---------------------------------------------------------------------------
# In-process FastMCP SSE server used by the behaviors below.
# ---------------------------------------------------------------------------

def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mcp_sse_server():
    """Spin up a minimal FastMCP SSE server in a background thread.

    Exposes tools covering every readOnlyHint state a real NAA server can
    produce: explicitly read-only, explicitly not read-only, and (the
    default today, before annotations are added) unannotated entirely.

    Yields the base URL (``http://127.0.0.1:<port>``).
    """
    import uvicorn
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    mcp_app = FastMCP("test-server")

    @mcp_app.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def ping() -> str:
        """Return a fixed string."""
        return "pong"

    @mcp_app.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def write_note(text: str) -> str:
        """A tool the server explicitly marks as not read-only."""
        return "saved"

    @mcp_app.tool()
    def unannotated_tool() -> str:
        """A tool with no annotations at all — must be blocked (fail closed)."""
        return "should never run"

    @mcp_app.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def failing_tool() -> str:
        """A read-only-declared tool that always raises server-side."""
        raise ValueError("boom")

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


# ---------------------------------------------------------------------------
# Behavior: only tools the server declared readOnlyHint=True are callable —
# an explicit readOnlyHint=False and a missing annotation are both blocked.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool_name", ["write_note", "unannotated_tool"])
def test_call_tool_raises_permission_error_for_non_readonly_tool(mcp_sse_server, tool_name):
    from agent.mcp_clients.sse_client import SseMcpClient
    url = f"{mcp_sse_server}/sse"
    with SseMcpClient(url=url) as client:
        with pytest.raises(PermissionError):
            client.call_tool(tool_name, {})


# ---------------------------------------------------------------------------
# Behavior: list_tools() returns only server-declared read-only tools
# ---------------------------------------------------------------------------

def test_list_tools_returns_only_readonly_declared_tools(mcp_sse_server):
    from agent.mcp_clients.sse_client import SseMcpClient
    url = f"{mcp_sse_server}/sse"
    with SseMcpClient(url=url) as client:
        tools = client.list_tools()
    names = {t["name"] for t in tools}
    assert names == {"ping", "failing_tool"}
    assert "inputSchema" in tools[0]


# ---------------------------------------------------------------------------
# Behavior: allowed tool call returns a string
# ---------------------------------------------------------------------------

def test_allowed_tool_call_returns_string(mcp_sse_server):
    from agent.mcp_clients.sse_client import SseMcpClient
    url = f"{mcp_sse_server}/sse"
    with SseMcpClient(url=url) as client:
        result = client.call_tool("ping", {})
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Behavior: call_tool() raises when the server reports isError=True, instead
# of silently returning the error text as if it were a normal result.
# ---------------------------------------------------------------------------

def test_call_tool_raises_when_server_reports_error(mcp_sse_server):
    from agent.mcp_clients.sse_client import SseMcpClient
    url = f"{mcp_sse_server}/sse"
    with SseMcpClient(url=url) as client:
        with pytest.raises(RuntimeError, match="boom"):
            client.call_tool("failing_tool", {})
