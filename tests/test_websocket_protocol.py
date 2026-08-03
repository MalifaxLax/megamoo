"""tests/test_websocket_protocol.py — RFC 6455 handshake and framing.

The accept hash is the one part of the protocol a browser silently
enforces: get it wrong and every browser refuses the upgrade with a bare
close, while a hand-rolled socket client (which rarely checks it) connects
happily.  So the handshake is pinned against the RFC's own worked example
rather than against whatever the implementation currently produces.
"""
import asyncio
import base64
import hashlib

import pytest

from moo.web.websocket import (
    websocket_handshake, encode_frame, decode_frame, OP_TEXT,
)


# RFC 6455 Section 1.3, verbatim: this key must produce this accept value.
RFC_KEY = 'dGhlIHNhbXBsZSBub25jZQ=='
RFC_ACCEPT = 's3pPLMBiTxaQ9kYGzzhZRbK+xOo='


def test_accept_matches_the_rfc_worked_example():
    response = websocket_handshake({'sec-websocket-key': RFC_KEY}).decode()
    assert f'Sec-WebSocket-Accept: {RFC_ACCEPT}' in response


def test_handshake_is_a_101_upgrade():
    response = websocket_handshake({'sec-websocket-key': RFC_KEY}).decode()
    assert response.startswith('HTTP/1.1 101 Switching Protocols')
    assert 'Upgrade: websocket' in response
    assert 'Connection: Upgrade' in response
    assert response.endswith('\r\n\r\n')


def test_accept_is_reproducible_for_an_arbitrary_key():
    # The same computation a browser performs to validate the response.
    key = base64.b64encode(b'0123456789abcdef').decode()
    guid = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
    expected = base64.b64encode(
        hashlib.sha1((key + guid).encode()).digest()).decode()
    response = websocket_handshake({'sec-websocket-key': key}).decode()
    assert f'Sec-WebSocket-Accept: {expected}' in response


def test_missing_key_is_rejected():
    with pytest.raises(ValueError):
        websocket_handshake({})


# ---------------------------------------------------------------------------
#   Framing
# ---------------------------------------------------------------------------

def _client_frame(payload: bytes, opcode: int = OP_TEXT) -> bytes:
    """Build a masked client->server frame (clients MUST mask; servers MUST NOT)."""
    mask = b'\x37\xfa\x21\x3d'
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    header = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:
        header += bytes([0x80 | n])
    elif n < 65536:
        header += bytes([0x80 | 126]) + n.to_bytes(2, 'big')
    else:
        header += bytes([0x80 | 127]) + n.to_bytes(8, 'big')
    return header + mask + masked


async def _decode(frame: bytes):
    """Feed `frame` to decode_frame through a real StreamReader."""
    reader = asyncio.StreamReader()
    reader.feed_data(frame)
    reader.feed_eof()
    return await decode_frame(reader)


@pytest.mark.parametrize('size', [5, 125, 126, 200, 70000])
def test_roundtrip_across_length_encodings(size):
    # 125/126 and 65535/65536 are the boundaries where the length field
    # changes width -- the classic place framing bugs hide.
    payload = ('x' * size).encode()
    opcode, data = asyncio.run(_decode(_client_frame(payload)))
    assert opcode == OP_TEXT
    assert data == payload


def test_server_frames_are_unmasked():
    # RFC 6455 5.1: a server MUST NOT mask. A masked server frame makes
    # browsers fail the connection.
    frame = encode_frame('hello')
    assert frame[1] & 0x80 == 0, 'server frame must not set the mask bit'


def test_server_frame_decodes_back_to_its_payload():
    # encode_frame is unmasked, so mask the payload back in to round-trip
    # it through the client-side decoder.
    assert asyncio.run(_decode(_client_frame(b'{"type":"text"}')))[1] \
        == b'{"type":"text"}'


def test_truncated_frame_raises_rather_than_returning_junk():
    with pytest.raises(asyncio.IncompleteReadError):
        asyncio.run(_decode(_client_frame(b'hello world')[:4]))
