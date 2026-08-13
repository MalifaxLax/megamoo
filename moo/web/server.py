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
# The one list of names a world may publish, shared with the login flow
# that advertises them.  Two copies would drift, and the failure would be
# a splash the client is told about and the server refuses to serve.
from ..login import SPLASH_IMAGE_NAMES

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
    # .jpeg and .webp are here because a world may publish its splash as
    # either; without them the file served correctly and arrived as
    # application/octet-stream, which a browser downloads instead of draws.
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
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
                 world_dir: str = '.',
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
        # The world's own directory -- where display_screen.txt and a
        # splash image live. Defaults to the working directory, which is
        # where the engine already looks for both.
        self._world_dir = Path(world_dir)
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
            # The query string is the client's, not the router's: it names
            # a file, and "/" and "/?session=wh" are the same file. Without
            # this every query 404s, which quietly broke the one escape
            # hatch the client documents -- ?ws=, read in client.js and
            # named in \connect's own refusal message as the way to reach
            # another origin. It could never have worked.
            path = parts[1].partition('?')[0] or '/'

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

            # Every world running on this machine, with a link to each.
            if method == 'GET' and path == '/worlds':
                await self._serve_worlds(writer)
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
    # Worlds index
    # -----------------------------------------------------------------

    @staticmethod
    def _running_worlds():
        """
        Every world with a live discovery file, newest name first.

        ``~/.megamoo/run`` holds one file per world that published itself
        (``megamoo --dev`` does).  A file outlives a crash, so each is
        checked against its pid before being believed -- otherwise the
        index would keep offering worlds that died days ago, which is
        worse than not having an index.
        """
        import json
        import os
        from pathlib import Path

        out = []
        run_dir = Path.home() / '.megamoo' / 'run'
        try:
            files = sorted(run_dir.glob('*.api.json'))
        except OSError:
            return out
        for f in files:
            try:
                info = json.loads(f.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            pid = info.get('pid')
            if isinstance(pid, int):
                try:
                    os.kill(pid, 0)      # signal 0: "are you there?"
                except OSError:
                    continue             # stale file, the world is gone
            web_port = info.get('web_port')
            if not isinstance(web_port, int):
                continue                 # nothing to link to
            db = Path(info.get('database') or '')
            out.append({
                # The directory, not the file: "sfdev" reads better than
                # "sf", and two worlds are far more likely to share a
                # database name than a directory.
                'name': db.parent.name or db.stem or 'world',
                'database': str(db),
                'web_port': web_port,
                'game_port': info.get('game_port'),
            })
        return out

    async def _serve_worlds(self, writer: asyncio.StreamWriter):
        """
        A page listing every world running on this machine.

        **Loopback only.**  The web port commonly binds 0.0.0.0, so this
        would otherwise tell anyone on the network which worlds exist
        here, where each one listens and what its files are called -- a
        map of the machine, handed out by a convenience page.  Answered
        with 404 rather than 403 for anyone else, so the page's existence
        is not advertised either.
        """
        peer = writer.get_extra_info('peername')
        host = (peer[0] if isinstance(peer, tuple) and peer else '') or ''
        if host not in ('127.0.0.1', '::1', ''):
            await self._send_response(writer, 404, 'Not Found')
            return

        import html
        rows = []
        for w in self._running_worlds():
            here = ' &nbsp;<span class="here">this one</span>' if (
                w['web_port'] == self._port) else ''
            game = (f"<span class=\"port\">telnet {w['game_port']}</span>"
                    if w['game_port'] else '')
            rows.append(
                f'<li><a href="http://{html.escape(host or "127.0.0.1")}'
                f':{w["web_port"]}/">{html.escape(w["name"])}</a>'
                f'{here}<br><span class="path">{html.escape(w["database"])}'
                f'</span> <span class="port">web {w["web_port"]}</span> '
                f'{game}</li>')

        listing = ('<ul>' + ''.join(rows) + '</ul>') if rows else (
            '<p class="empty">No worlds are publishing themselves. A world '
            'started with <code>megamoo --dev</code> appears here.</p>')

        body = f"""<!doctype html>
<meta charset="utf-8">
<title>MegaMOO worlds</title>
<style>
  body {{ background:#0c0e11; color:#b6bcc6; font:14px ui-monospace,Menlo,monospace;
         margin:0; padding:40px 24px; }}
  h1 {{ font-size:12px; letter-spacing:.08em; text-transform:uppercase;
        color:#7c8695; font-weight:700; margin:0 0 20px; }}
  ul {{ list-style:none; margin:0; padding:0; max-width:640px; }}
  li {{ padding:12px 0; border-bottom:1px solid #22262d; }}
  a {{ color:#e8c15c; font-size:16px; text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  .path {{ color:#4c5563; font-size:12px; }}
  .port {{ color:#7c8695; font-size:12px; }}
  .here {{ color:#63a95f; font-size:11px; text-transform:uppercase;
           letter-spacing:.05em; }}
  .empty {{ color:#7c8695; }}
  code {{ color:#b6bcc6; }}
</style>
<h1>MegaMOO &mdash; worlds on this machine</h1>
{listing}
""".encode()

        header = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
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

        # A world's own splash image is served from the world's directory,
        # not from the installed package. It belongs to the game rather
        # than the engine -- it travels in the directory `megamoo init`
        # creates, beside display_screen.txt, and is version-controlled by
        # whoever owns the world.
        #
        # Only the exact names in SPLASH_IMAGE_NAMES resolve here. This is
        # an allow-list rather than a second document root on purpose: a
        # directory the operator did not choose to publish must not become
        # browsable because the client asked nicely.
        name = path.lstrip('/')
        if name in SPLASH_IMAGE_NAMES:
            root, file_path = self._world_dir, self._world_dir / name
        else:
            root, file_path = self._static_dir, self._static_dir / name

        # Verify the resolved path is within the directory it came from
        # (defense-in-depth against symlink traversal)
        try:
            file_path = file_path.resolve()
            if not file_path.is_relative_to(root.resolve()):
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
