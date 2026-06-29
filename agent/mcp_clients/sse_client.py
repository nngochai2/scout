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

    Only tools in ``read_only_tools`` may be called; any other name raises
    ``PermissionError`` immediately, before any network activity.

    Usage::

        with SseMcpClient("http://host/sse", ["search_notes"]) as c:
            result = c.call_tool("search_notes", {"query": "auth"})
    """

    def __init__(self, url: str, read_only_tools: list[str], connect_timeout: float = 10.0) -> None:
        self._url = url
        self._allowed: frozenset[str] = frozenset(read_only_tools)
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
            return httpx.AsyncClient(
                headers=headers or {},
                timeout=timeout,
                auth=auth,
                proxies={f"all://{host}": None} if host else {},
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
        """Open the SSE connection and initialise the MCP session.

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

    def call_tool(self, name: str, args: dict) -> str:
        """Call *name* on the remote MCP server and return the text result.

        Raises:
            PermissionError: if *name* is not in the allowlist.
            RuntimeError:    if ``connect()`` has not been called.
        """
        if name not in self._allowed:
            raise PermissionError(
                f"Tool '{name}' is not in the read-only allowlist for this client. "
                f"Allowed: {sorted(self._allowed)}"
            )
        if self._session is None:
            raise RuntimeError("Call connect() before call_tool().")
        result = self._run(self._session.call_tool(name, args))
        texts = [c.text for c in result.content if hasattr(c, "text")]
        return "\n\n".join(texts) if texts else "(no results)"

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
