"""
MegaMOO Web Client Package

This package provides the WebSocket-based web client interface for
MegaMOO.  It allows players to connect to the game through a web
browser instead of (or in addition to) a traditional telnet/MUD client.

Package components
------------------

* **server.py** -- ``WebServer`` class: HTTP static file server that
  also handles WebSocket upgrade requests on the ``/ws`` path.

* **connection.py** -- ``WebSocketConnection`` class: manages an
  individual web client session, mirroring the ``PlayerConnection``
  interface used by telnet clients.

* **websocket.py** -- Low-level RFC 6455 WebSocket protocol:
  handshake, frame encoding/decoding, ping/pong, close frames.

* **color.py** -- Converts MOO ``%`` color codes to HTML ``<span>``
  tags with CSS classes (the web equivalent of ANSI escape codes
  used by telnet clients).

The web client's static files (HTML, CSS, JavaScript) are served
from a configurable directory and communicate with the server using
JSON-formatted WebSocket messages.
"""
