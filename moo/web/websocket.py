"""
RFC 6455 WebSocket Protocol Implementation

Pure-stdlib implementation of the WebSocket protocol for MegaMOO's web
client.  Handles the HTTP upgrade handshake, frame encoding (server to
client), and frame decoding (client to server, including client-side
masking as required by RFC 6455).

This module does NOT use any third-party WebSocket libraries -- it
implements the protocol directly using ``hashlib``, ``base64``,
``struct``, and ``asyncio`` from the Python standard library.

Protocol overview
-----------------

1. **Handshake** -- The client sends an HTTP GET request with
   ``Upgrade: websocket`` headers.  The server responds with HTTP 101
   and a ``Sec-WebSocket-Accept`` header computed from the client's
   key and the RFC 6455 magic GUID.

2. **Framing** -- Data is exchanged in frames.  Each frame has:
   - FIN bit (1 = final fragment)
   - Opcode (text=0x1, close=0x8, ping=0x9, pong=0xA)
   - Mask bit + masking key (client-to-server frames MUST be masked)
   - Payload length (7-bit, 16-bit, or 64-bit extended)
   - Payload data

3. **Server frames are NOT masked** (per RFC 6455 Section 5.1).
   Client frames are always masked and must be unmasked on receipt.

Limitations
-----------

* Fragmented frames (FIN=0) are not supported and will raise
  ``ConnectionError``.
* Maximum frame size is 1 MB (configurable via ``_MAX_FRAME_SIZE``).
* Binary frames are not used by MegaMOO (all communication is
  JSON-over-text-frames).

See also
--------

* ``connection.py`` -- Uses this module for WebSocket I/O.
* ``server.py`` -- Uses ``websocket_handshake()`` during HTTP upgrade.
"""

import asyncio
import base64
import hashlib
import struct
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# RFC 6455 Section 4.2.2 -- magic GUID used in the handshake accept hash.
# This exact string is normative: the client computes the same hash and
# drops the connection if the server's Sec-WebSocket-Accept disagrees, so a
# single wrong character makes every browser refuse the upgrade (while
# hand-rolled socket clients, which rarely verify it, connect happily).
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# WebSocket frame opcodes
OP_TEXT = 0x1     # Text frame (UTF-8 encoded payload)
OP_CLOSE = 0x8    # Connection close frame
OP_PING = 0x9     # Ping frame (keep-alive)
OP_PONG = 0xA     # Pong frame (response to ping)

# Maximum allowed payload size for a single frame (1 MB)
_MAX_FRAME_SIZE = 1_048_576


# =============================================================================
# Handshake
# =============================================================================

def websocket_handshake(headers: dict) -> bytes:
    """
    Generate the HTTP 101 Switching Protocols response for a WebSocket
    upgrade request.

    Computes the ``Sec-WebSocket-Accept`` value by concatenating the
    client's ``Sec-WebSocket-Key`` with the RFC 6455 magic GUID,
    taking the SHA-1 hash, and base64-encoding the result.

    Args:
        headers: Parsed HTTP request headers with **lowercase** keys.
                 Must contain ``'sec-websocket-key'``.

    Returns:
        Complete HTTP response bytes (including trailing ``\\r\\n\\r\\n``)
        ready to be written to the socket.

    Raises:
        ValueError: If the ``Sec-WebSocket-Key`` header is missing.
    """
    key = headers.get("sec-websocket-key", "")
    if not key:
        raise ValueError("Missing Sec-WebSocket-Key header")

    # Compute accept hash per RFC 6455 Section 4.2.2
    accept = base64.b64encode(
        hashlib.sha1((key + _WS_GUID).encode()).digest()
    ).decode()

    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    )
    return response.encode()


# =============================================================================
# Frame Encoding (Server -> Client)
# =============================================================================

def encode_frame(payload: str | bytes, opcode: int = OP_TEXT) -> bytes:
    """
    Encode a WebSocket frame for sending from server to client.

    Server-to-client frames are **not masked** (per RFC 6455 Section
    5.1).  The FIN bit is always set (no fragmentation support).

    The payload length encoding follows the RFC 6455 scheme:
    - 0-125: length in a single byte
    - 126-65535: 2-byte extended length
    - 65536+: 8-byte extended length

    Args:
        payload: Text string or bytes to send.  Strings are encoded
                 as UTF-8.
        opcode:  Frame opcode (default: ``OP_TEXT``).

    Returns:
        Complete WebSocket frame as bytes, ready to write to the socket.
    """
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    length = len(data)

    # First byte: FIN bit (0x80) | opcode
    header = bytes([0x80 | opcode])

    # Second byte onwards: payload length (mask bit = 0 for server frames)
    if length < 126:
        header += bytes([length])
    elif length < 65536:
        header += bytes([126]) + struct.pack("!H", length)
    else:
        header += bytes([127]) + struct.pack("!Q", length)

    return header + data


# =============================================================================
# Frame Decoding (Client -> Server)
# =============================================================================

async def decode_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    """
    Read and decode a single WebSocket frame from an asyncio reader.

    Client-to-server frames are **always masked** (RFC 6455 Section
    5.1).  This function handles unmasking automatically by XOR-ing
    each payload byte with the corresponding byte of the 4-byte
    masking key.

    Args:
        reader: ``asyncio.StreamReader`` connected to the client socket.

    Returns:
        Tuple of ``(opcode, payload_bytes)`` where:
        - *opcode* is the frame type (``OP_TEXT``, ``OP_CLOSE``, etc.)
        - *payload_bytes* is the unmasked payload data

    Raises:
        ConnectionError: If the frame is fragmented (FIN=0), exceeds
            ``_MAX_FRAME_SIZE``, or the connection drops.
        asyncio.IncompleteReadError: If the connection is closed
            mid-frame.
    """
    # Read first 2 bytes: FIN/opcode byte + mask/length byte
    head = await reader.readexactly(2)
    fin = bool(head[0] & 0x80)       # FIN bit: is this the final fragment?
    opcode = head[0] & 0x0F          # Lower 4 bits = opcode
    masked = bool(head[1] & 0x80)    # Mask bit: is the payload masked?
    length = head[1] & 0x7F          # Lower 7 bits = payload length (or marker)

    if not fin:
        raise ConnectionError("Fragmented WebSocket frames not supported")

    # Extended payload length (if length marker is 126 or 127)
    if length == 126:
        raw = await reader.readexactly(2)
        length = struct.unpack("!H", raw)[0]
    elif length == 127:
        raw = await reader.readexactly(8)
        length = struct.unpack("!Q", raw)[0]

    if length > _MAX_FRAME_SIZE:
        raise ConnectionError(f"Frame too large: {length} bytes")

    # Read 4-byte masking key (present only if mask bit is set)
    mask_key = await reader.readexactly(4) if masked else None

    # Read the payload data
    payload = await reader.readexactly(length)

    # Unmask the payload by XOR-ing with the rotating masking key
    if mask_key:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

    return opcode, payload


# =============================================================================
# Convenience Frame Builders
# =============================================================================

def encode_close(code: int = 1000, reason: str = "") -> bytes:
    """
    Encode a WebSocket close frame.

    The close frame payload consists of a 2-byte status code followed
    by an optional UTF-8 reason string.

    Args:
        code:   Close status code (default: 1000 = Normal Closure).
                Common codes: 1000 (normal), 1001 (going away),
                1002 (protocol error), 1003 (unsupported data).
        reason: Optional human-readable close reason.

    Returns:
        Complete WebSocket close frame bytes.
    """
    payload = struct.pack("!H", code) + reason.encode("utf-8")
    return encode_frame(payload, opcode=OP_CLOSE)


def encode_pong(data: bytes) -> bytes:
    """
    Encode a WebSocket pong frame in response to a ping.

    Per RFC 6455, a pong frame must echo back the exact payload that
    was received in the ping frame.

    Args:
        data: The ping payload to echo back.

    Returns:
        Complete WebSocket pong frame bytes.
    """
    return encode_frame(data, opcode=OP_PONG)
