"""Sync wrapper around an MCP server reachable via SSE transport.

The entire connection lifecycle (open → initialize → wait → close) runs inside
a single long-lived coroutine so that anyio's cancel scopes are entered and
exited within the same task — a requirement of the mcp SSE client.

The public interface is synchronous; threading bridges the async internals.
"""
import asyncio
import threading
from urllib.parse import urlparse

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client


class SseMcpClient:
    """Generic read-only sync client for an SSE MCP server.

    The allowlist is not hand-maintained — it's discovered at ``connect()``
    time from the server's own declared ``ToolAnnotations.readOnlyHint`` on
    each tool (see the MCP spec). A tool is only callable if the server
    explicitly marked it ``readOnlyHint=True``; anything unset or false is
    treated as unsafe (fail closed), so a server author forgetting to
    annotate a new mutating tool blocks it by default instead of exposing it.
    This also means Scout never has to hardcode or guess tool names per
    server — it can only ever call a tool name the connected server actually
    has, since the allowlist is a filtered view of the server's live tool list.

    Usage::

        with SseMcpClient("http://host/sse") as c:
            result = c.call_tool("search_notes", {"query": "auth"})
    """

    def __init__(self, url: str, connect_timeout: float = 10.0) -> None:
        self._url = url
        self._connect_timeout = connect_timeout

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

        self._session: ClientSession | None = None
        self._connected = threading.Event()
        self._connect_error: Exception | None = None
        # asyncio.Event created inside the background loop in _session_lifecycle
        self._close_event: asyncio.Event | None = None
        self._lifecycle_future = None  # concurrent.futures.Future for the lifecycle task

        # Populated at connect() time from the server's declared annotations —
        # see _fetch_read_only_tools(). None means "not connected yet".
        self._read_only_tools: list[dict] | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self, coro, timeout: float = 30.0):
        """Run *coro* in the background event loop and block until done."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)

    async def _session_lifecycle(self) -> None:
        """Single long-lived coroutine owning the full SSE connection lifecycle.

        Creating and destroying anyio task groups (used by sse_client internally)
        must happen within the same task.  Keeping everything here satisfies that.
        """
        self._close_event = asyncio.Event()
        host = urlparse(self._url).hostname or ""

        def _factory(headers=None, timeout=None, auth=None):
            mounts = {f"all://{host}": httpx.AsyncHTTPTransport()} if host else {}
            return httpx.AsyncClient(
                headers=headers or {},
                timeout=timeout,
                auth=auth,
                mounts=mounts,
            )

        try:
            async with sse_client(self._url, httpx_client_factory=_factory) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session
                    self._connected.set()          # unblock connect()
                    await self._close_event.wait() # hold until close() signals
        except Exception as exc:
            # anyio wraps TaskGroup failures in an ExceptionGroup; unwrap to expose root cause
            if hasattr(exc, 'exceptions') and exc.exceptions:
                self._connect_error = exc.exceptions[0]
            else:
                self._connect_error = exc
            self._connected.set()                  # unblock connect() with error

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the SSE connection, initialise the MCP session, and discover
        which of the server's tools are safe to call.

        Raises:
            ConnectionError: if the server is unreachable, with the URL in
                the message so callers can log it meaningfully.
        """
        self._lifecycle_future = asyncio.run_coroutine_threadsafe(
            self._session_lifecycle(), self._loop
        )
        ok = self._connected.wait(timeout=self._connect_timeout)
        if not ok or self._connect_error is not None:
            err = self._connect_error or TimeoutError("timed out waiting for server")
            raise ConnectionError(
                f"Cannot connect to MCP server at {self._url}: {err}"
            ) from (self._connect_error or None)
        self._read_only_tools = self._fetch_read_only_tools()

    def _fetch_read_only_tools(self) -> list[dict]:
        """Query the live server and keep only tools it declared read-only.

        A tool is kept only if the server set ``annotations.readOnlyHint =
        True``. Missing annotations or ``readOnlyHint=False`` are both
        treated as unsafe — Scout never infers safety from a tool's name.
        """
        result = self._run(self._session.list_tools())
        return [
            {"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema}
            for t in result.tools
            if t.annotations is not None and t.annotations.readOnlyHint is True
        ]

    def call_tool(self, name: str, args: dict) -> str:
        """Call *name* on the remote MCP server and return the text result.

        Raises:
            PermissionError: if *name* is not one of the tools the server
                declared read-only.
            RuntimeError:    if ``connect()`` has not been called, or if the
                server reports ``isError`` (a tool-side failure) rather than
                letting that error text pass through as if it were evidence.
        """
        if self._read_only_tools is None:
            raise RuntimeError("Call connect() before call_tool().")
        allowed_names = {t["name"] for t in self._read_only_tools}
        if name not in allowed_names:
            raise PermissionError(
                f"Tool '{name}' is not declared read-only by this server. "
                f"Allowed: {sorted(allowed_names)}"
            )
        result = self._run(self._session.call_tool(name, args))
        texts = [c.text for c in result.content if hasattr(c, "text")]
        text = "\n\n".join(texts) if texts else "(no results)"
        if result.isError:
            raise RuntimeError(text)
        return text

    def list_tools(self) -> list[dict]:
        """Return the read-only tool schemas discovered at ``connect()`` time.

        Raises:
            RuntimeError: if ``connect()`` has not been called.
        """
        if self._read_only_tools is None:
            raise RuntimeError("Call connect() before list_tools().")
        return self._read_only_tools

    def close(self) -> None:
        """Signal the lifecycle coroutine to shut down and stop the event loop."""
        if self._close_event is not None:
            # Signal from the main thread into the background loop safely
            self._loop.call_soon_threadsafe(self._close_event.set)
        if self._lifecycle_future is not None:
            try:
                self._lifecycle_future.result(timeout=5.0)
            except Exception:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)

    def __enter__(self) -> "SseMcpClient":
        self.connect()
        return self

    def __exit__(self, *args) -> None:
        self.close()
