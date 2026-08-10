"""
HTTP Static File Server + WebSocket Upgrade Handler

This module implements the ``WebServer`` class, which is MegaMOO's
combined HTTP and WebSocket server for the web client.  It serves two
purposes:

1. **Static file serving** -- Serves the web client's HTML, CSS,
   JavaScript, images, and font files over HTTP from a configurable
   directory on disk.

2. **WebSocket upgrade** -- When a client requests ``/ws`` with the
   appropriate ``Upgrade: websocket`` headers, the connection is
   upgraded to a WebSocket and handed off to a
   ``WebSocketConnection`` instance (defined in ``connection.py``).

The server runs as an asyncio TCP server.  Each incoming TCP connection
is routed to either static file serving or WebSocket handling based on
the HTTP request path and headers.

Architecture
------------

::

    Browser
      |
      |  HTTP GET /index.html  ->  _serve_static()  -> sends file
      |  HTTP GET /ws          ->  _handle_websocket()  -> WebSocketConnection
      |
    WebServer (asyncio TCP server)
      |
    MegaMOOServer (game server)

Security
--------

* Directory traversal attacks are blocked (``..`` in paths is rejected).
* File paths are resolved and verified to be within the static directory.
* Only GET requests are accepted; other methods return 405.

Copyright (c) 2026
License: MIT
"""

import asyncio
import collections
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote

from .connection import WebSocketConnection

if TYPE_CHECKING:
    from ..server import MegaMOOServer

logger = logging.getLogger('megamoo.web')


# =============================================================================
# Content Type Mapping
# =============================================================================

# Maps file extensions to HTTP Content-Type headers for static file serving.
_CONTENT_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.woff2': 'font/woff2',
    '.woff': 'font/woff',
    '.ttf': 'font/ttf',
    # The Lua scripting host's interpreter.  This exact type is required:
    # WebAssembly.instantiateStreaming rejects anything else, so serving it
    # as octet-stream silently breaks Lua scripting.
    '.wasm': 'application/wasm',
    '.map': 'application/json',
    '.txt': 'text/plain; charset=utf-8',
}


# =============================================================================
# WebServer
# =============================================================================

class WebServer:
    """
    Combined HTTP static file server and WebSocket upgrade handler for
    the MegaMOO web client.

    The server listens on a configurable host and port.  Plain HTTP GET
    requests are served from a static directory.  Requests to ``/ws``
    with WebSocket upgrade headers are upgraded and handed off to
    ``WebSocketConnection`` instances that run the same login flow and
    command loop as telnet connections.

    Attributes:
        _server:       Reference to the parent ``MegaMOOServer`` instance.
        _host:         Bind address (e.g. ``'0.0.0.0'``).
        _port:         Bind port (e.g. ``8080``).
        _static_dir:   ``Path`` to the directory containing web client
                       static files (HTML, CSS, JS).
        _tcp_server:   The underlying ``asyncio.Server`` instance
                       (set after :meth:`start`).
        _connections:  Set of active ``WebSocketConnection`` instances.
    """

    def __init__(self, server: 'MegaMOOServer', host: str, port: int,
                 static_dir: str, allowed_origins=None, scan_limit: int = 1,
                 ssl_context=None):
        """
        Initialise the web server.

        Args:
            server:     The parent ``MegaMOOServer`` instance (provides
                        access to the database, config, and command
                        execution).
            host:       Address to bind to (e.g. ``'0.0.0.0'``,
                        ``'127.0.0.1'``).
            port:       First TCP port to try.
            static_dir: Filesystem path to the directory containing the
                        web client's static files.
            allowed_origins: Browser origins permitted to open a
                        WebSocket, *in addition to* the origin the client
                        was served from.  Accepts a list, or a
                        comma-separated string (which is what an
                        environment variable delivers).  Empty/``None``
                        means same-origin only; a literal ``'*'`` allows
                        any origin.  See ``_origin_allowed``.
            scan_limit: How many consecutive ports to try.  ``1`` pins
                        ``port`` exactly, so a conflict raises.
            ssl_context: An ``ssl.SSLContext`` to serve HTTPS with, or
                        ``None`` for plain HTTP.  This is a flag on the
                        one port rather than a second listener the way
                        the game's TLS is: a browser is not telnet, so
                        nothing here has to keep speaking plaintext.
                        It is also what lets the client use ``wss:`` --
                        client.js picks the socket scheme from
                        ``location.protocol``, so over HTTP it can only
                        ever open an unencrypted socket, whatever the
                        game listener is doing.
        """
        self._server = server
        self._host = host
        self._port = port
        self._scan_limit = scan_limit
        self._ssl_context = ssl_context
        self._static_dir = Path(static_dir)
        self._tcp_server = None
        self._connections: set = set()
        # Per-IP connection rate limiting
        self._conn_timestamps: dict = {}
        self._conn_rate_limit = 5       # max connections per window
        self._conn_rate_window = 10.0   # window in seconds
        # Origin allow-list.  A bare string arrives from the environment
        # (MEGAMOO_NETWORK_WEBSOCKET_ALLOWED_ORIGINS=https://a,https://b),
        # so accept both shapes rather than silently treating a string as
        # a list of one-character origins.
        if isinstance(allowed_origins, str):
            allowed_origins = [o.strip() for o in allowed_origins.split(',')]
        self._allowed_origins = [o.rstrip('/')
                                 for o in (allowed_origins or []) if o]

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    async def start(self):
        """
        Start listening for HTTP and WebSocket connections.

        Binds the first free port at or above the configured one (or pins
        it exactly when ``scan_limit`` is 1).  Each incoming connection is
        handled by :meth:`_handle_request`.  The port actually won is
        stored on ``self._port`` so the caller can log and advertise it.
        """
        from ..server import listen_walking_ports

        first = self._port
        self._tcp_server, self._port = await listen_walking_ports(
            self._handle_request, self._host, first, self._scan_limit,
            ssl=self._ssl_context
        )
        if self._port != first:
            logger.warning(f"Web port {first} in use; "
                           f"auto-selected {self._port}")
        # A host:port in a log line is not an invitation.  Print the URL
        # somebody can actually click, using a host a browser will accept
        # -- 0.0.0.0 means "every interface" to a listener and nothing at
        # all to a browser.
        shown = ('127.0.0.1' if self._host in ('0.0.0.0', '', None)
                 else self._host)
        scheme = 'https' if self._ssl_context else 'http'
        logger.info(f"Web client listening on {self._host}:{self._port} "
                    f"({scheme})")
        print(f"\n    Play in a browser:  {scheme}://{shown}:{self._port}/\n",
              flush=True)

    @property
    def port(self) -> int:
        """The port the listener actually bound (set by :meth:`start`)."""
        return self._port

    # -----------------------------------------------------------------
    # Rate limiting
    # -----------------------------------------------------------------

    def _allow_new_session(self, writer: asyncio.StreamWriter) -> bool:
        """
        Whether this IP may open another game session right now.

        Scoped to WebSocket upgrades on purpose.  Applying it to *every*
        HTTP request throttles the client's own page load -- index.html,
        the stylesheet and the scripts are four requests before the socket
        is even attempted, so a single visit exhausted the budget and the
        upgrade was refused.  Static files are cheap and stateless; a
        session costs a login slot and a task, and is what needs guarding.
        """
        peername = writer.get_extra_info('peername')
        ip = peername[0] if peername else 'unknown'
        now = time.monotonic()

        timestamps = self._conn_timestamps.get(ip)
        if timestamps is None:
            timestamps = collections.deque()
            self._conn_timestamps[ip] = timestamps
        while timestamps and timestamps[0] <= now - self._conn_rate_window:
            timestamps.popleft()

        if len(timestamps) >= self._conn_rate_limit:
            logger.warning(f"Session rate limit exceeded for {ip}")
            return False

        timestamps.append(now)
        return True

    # -----------------------------------------------------------------
    # Origin checking
    # -----------------------------------------------------------------

    def _origin_allowed(self, headers: dict) -> bool:
        """
        Whether a WebSocket upgrade may proceed, based on ``Origin``.

        The browser same-origin policy does **not** apply to WebSockets:
        without this check, any page a logged-in player visits could open
        a socket to the game and drive it as them.  ``Origin`` is set by
        the browser and cannot be forged by page JavaScript, which is what
        makes it usable here.

        The default with no allow-list configured is **same origin only**:
        the page that opens the socket must have come from the host this
        request was addressed to.  That is the whole of the common case --
        a browser loads the client from this server and opens a socket
        back to it -- and it needs no configuration, which matters because
        the configuration was the part nobody did.

        It is also the only default that holds up behind a reverse proxy.
        A rule based on which interface the server bound cannot: the proxy
        makes the world public whatever the bind address is, and the
        attack arrives through the proxy like any other request.  Comparing
        ``Origin`` against ``Host`` compares two things the attacker does
        not control together -- the browser sets ``Origin`` to the page's
        own origin, and ``Host`` is whichever name the socket was opened
        to.

        ``websocket_allowed_origins`` then *adds* origins, for a client
        served from somewhere other than the game (a CDN, a separate front
        end). A literal ``'*'`` restores the old accept-anything behaviour
        for anyone who wants it back.

        Non-browser clients send no ``Origin`` at all and are always
        allowed: they are not subject to the attack this defends against.
        """
        origin = headers.get('origin')
        if origin is None:
            return True
        if '*' in self._allowed_origins:
            return True
        origin = origin.rstrip('/')
        if origin in self._allowed_origins:
            return True
        # Same origin: compare the authority halves, since Origin carries
        # a scheme and Host does not.  Behind a TLS-terminating proxy the
        # page is https and this hop is plain, so the schemes legitimately
        # differ and comparing them would reject the good case.
        host = (headers.get('host') or '').rstrip('/')
        return bool(host) and origin.partition('://')[2] == host

    async def stop(self):
        """
        Stop the server and close all active WebSocket connections.

        Marks all connections as disconnected, clears the connection
        set, and shuts down the underlying TCP server.
        """
        for conn in list(self._connections):
            conn._disconnected = True
        self._connections.clear()

        if self._tcp_server:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()
            logger.info("Web server stopped")

    # -----------------------------------------------------------------
    # Request Routing
    # -----------------------------------------------------------------

    async def _handle_request(self, reader: asyncio.StreamReader,
                              writer: asyncio.StreamWriter):
        """
        Route an incoming TCP connection to HTTP or WebSocket handling.

        Reads the HTTP request line and headers, then:

        * If the path is ``/ws`` and the headers include
          ``Upgrade: websocket``, delegates to :meth:`_handle_websocket`.
        * If the method is GET, delegates to :meth:`_serve_static`.
        * Otherwise, sends a 405 Method Not Allowed response.

        The writer is closed after handling unless the connection was
        upgraded to WebSocket (in which case the WebSocketConnection
        manages the socket lifecycle).

        Args:
            reader: asyncio stream reader for the TCP connection.
            writer: asyncio stream writer for the TCP connection.
        """
        is_websocket = False
        try:
            # Read the HTTP request line (e.g. "GET /index.html HTTP/1.1")
            request_line = await asyncio.wait_for(
                reader.readline(), timeout=10.0
            )
            if not request_line:
                return

            decoded = request_line.decode('utf-8', errors='ignore').strip()
            parts = decoded.split()
            if len(parts) < 2:
                return

            method = parts[0]
            path = parts[1]

            # Read all HTTP headers into a dict with lowercase keys
            headers = {}
            while True:
                line = await asyncio.wait_for(
                    reader.readline(), timeout=10.0
                )
                if not line or line == b'\r\n' or line == b'\n':
                    break
                h = line.decode('utf-8', errors='ignore').strip()
                if ':' in h:
                    key, value = h.split(':', 1)
                    headers[key.strip().lower()] = value.strip()

            # WebSocket upgrade on /ws.  _handle_websocket reports whether
            # it took ownership of the socket: a *rejected* upgrade (bad
            # origin, failed handshake) has not, and still needs closing
            # by the finally block below.
            if (path == '/ws'
                    and headers.get('upgrade', '').lower() == 'websocket'):
                if not self._allow_new_session(writer):
                    await self._send_response(writer, 429, 'Too Many Requests')
                    return
                is_websocket = await self._handle_websocket(
                    reader, writer, headers)
                return

            # Build stamp, so a page can tell it has gone stale.
            if method == 'GET' and path == '/build':
                await self._serve_build_stamp(writer)
                return

            # Static file serving for GET requests
            if method == 'GET':
                await self._serve_static(writer, path)
            else:
                await self._send_response(writer, 405, 'Method Not Allowed')

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.debug(f"Request handling error: {e}")
        finally:
            # Only close the socket if we did NOT upgrade to WebSocket
            # (WebSocketConnection manages its own socket lifecycle)
            if not is_websocket:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

    # -----------------------------------------------------------------
    # WebSocket Handling
    # -----------------------------------------------------------------

    async def _handle_websocket(self, reader: asyncio.StreamReader,
                                writer: asyncio.StreamWriter,
                                headers: dict):
        """
        Complete the WebSocket handshake and start a connection session.

        Sends the HTTP 101 response, creates a ``WebSocketConnection``
        instance, registers it in the active connections set, and runs
        the connection's login + command loop.  The connection is
        removed from the set when it terminates.

        Args:
            reader:  asyncio stream reader for the TCP connection.
            writer:  asyncio stream writer for the TCP connection.
            headers: Parsed HTTP headers (lowercase keys) from the
                     upgrade request.

        Returns:
            bool: ``True`` if the socket was upgraded and this method now
            owns its lifecycle; ``False`` if the upgrade was refused, in
            which case the caller must close it.
        """
        from .websocket import websocket_handshake

        if not self._origin_allowed(headers):
            logger.warning(
                f"Rejected WebSocket upgrade from disallowed origin "
                f"{headers.get('origin')!r}")
            await self._send_response(writer, 403, 'Forbidden')
            return False

        try:
            response = websocket_handshake(headers)
            writer.write(response)
            await writer.drain()
        except Exception as e:
            logger.error(f"WebSocket handshake failed: {e}")
            await self._send_response(writer, 400, 'Bad Request')
            return False

        conn = WebSocketConnection(reader, writer, self._server)
        self._connections.add(conn)
        try:
            await conn._run_after_handshake()
        finally:
            self._connections.discard(conn)
        return True

    # -----------------------------------------------------------------
    # Build stamp
    # -----------------------------------------------------------------

    async def _serve_build_stamp(self, writer: asyncio.StreamWriter):
        """
        Report the newest modification time across the client's files.

        The client auto-reconnects its WebSocket when the server restarts,
        *without* reloading the page.  That is the right behaviour for a
        dropped connection, but it means a player can keep running
        JavaScript from before a deploy indefinitely -- and a stale client
        misbehaving looks exactly like a server bug.  The page reads this
        on load and on every reconnect, and says so when it changes.

        Directory mtimes are ignored: editing a file updates its parent
        directory too, which would be the same signal counted twice.
        """
        newest = 0.0
        try:
            for path in self._static_dir.rglob('*'):
                if path.is_file():
                    newest = max(newest, path.stat().st_mtime)
        except OSError:
            pass

        body = f'{{"build":"{newest:.0f}"}}'.encode()
        header = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n"
            "\r\n"
        )
        try:
            writer.write(header.encode() + body)
            await writer.drain()
        except Exception:
            pass

    # -----------------------------------------------------------------
    # Static File Serving
    # -----------------------------------------------------------------

    async def _serve_static(self, writer: asyncio.StreamWriter, path: str):
        """
        Serve a static file from the web client directory.

        Handles URL-decoding, directory traversal prevention, default
        index file mapping (``/`` -> ``/index.html``), content type
        detection, and file reading.

        Args:
            writer: asyncio stream writer to send the response to.
            path:   URL path from the HTTP request (e.g. ``/style.css``).
        """
        # URL-decode the path (handles %20, etc.)
        path = unquote(path)

        # Security: reject any path containing '..' to prevent
        # directory traversal attacks
        if '..' in path:
            await self._send_response(writer, 403, 'Forbidden')
            return

        # Map root path to index.html
        if path == '/':
            path = '/index.html'

        # Resolve the full filesystem path
        file_path = self._static_dir / path.lstrip('/')

        # Verify the resolved path is within the static directory
        # (defense-in-depth against symlink traversal)
        try:
            file_path = file_path.resolve()
            if not file_path.is_relative_to(self._static_dir.resolve()):
                await self._send_response(writer, 403, 'Forbidden')
                return
        except (ValueError, OSError):
            await self._send_response(writer, 400, 'Bad Request')
            return

        if not file_path.is_file():
            await self._send_response(writer, 404, 'Not Found')
            return

        # Determine content type from file extension
        suffix = file_path.suffix.lower()
        content_type = _CONTENT_TYPES.get(suffix, 'application/octet-stream')

        # Read the file and send it with appropriate headers
        try:
            data = file_path.read_bytes()
            header = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: {content_type}\r\n"
                f"Content-Length: {len(data)}\r\n"
                f"Cache-Control: no-cache\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            )
            writer.write(header.encode() + data)
            await writer.drain()
        except Exception as e:
            logger.error(f"Error serving {file_path}: {e}")
            await self._send_response(writer, 500, 'Internal Server Error')

    # -----------------------------------------------------------------
    # HTTP Response Helper
    # -----------------------------------------------------------------

    async def _send_response(self, writer: asyncio.StreamWriter,
                             status: int, message: str):
        """
        Send a simple HTTP text response with a status code and message.

        Used for error responses (400, 403, 404, 405, 500).  The
        response body is the status code and message as plain text.

        Args:
            writer:  asyncio stream writer to send the response to.
            status:  HTTP status code (e.g. 404).
            message: HTTP status message (e.g. ``'Not Found'``).
        """
        body = f"{status} {message}\n".encode()
        header = (
            f"HTTP/1.1 {status} {message}\r\n"
            f"Content-Type: text/plain\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        try:
            writer.write(header.encode() + body)
            await writer.drain()
        except Exception:
            pass
