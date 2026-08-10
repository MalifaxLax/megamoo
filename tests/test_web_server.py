"""Unit tests for the web client's HTTP/WebSocket server.

No game server involved: a WebServer is started directly against a stub,
with real sockets on loopback.  Covers port auto-selection (mirroring the
API's rules) and the Origin allow-list that guards WebSocket upgrades.
"""
import asyncio
import base64
import os

import pytest

from moo.web.server import WebServer


def _free_port() -> int:
    """A port that was free a moment ago -- good enough as a scan base."""
    import socket
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


async def _occupy(port):
    """Hold `port` open so the web server has to look elsewhere."""
    async def handle(reader, writer):
        writer.close()
    return await asyncio.start_server(handle, '127.0.0.1', port)


def _make(tmp_path, port, **kwargs):
    return WebServer(None, '127.0.0.1', port, str(tmp_path), **kwargs)


async def _upgrade_request(port, origin=None):
    """Send a WebSocket upgrade and return the response's status line."""
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    key = base64.b64encode(os.urandom(16)).decode()
    lines = [
        'GET /ws HTTP/1.1',
        f'Host: 127.0.0.1:{port}',
        'Upgrade: websocket',
        'Connection: Upgrade',
        f'Sec-WebSocket-Key: {key}',
        'Sec-WebSocket-Version: 13',
    ]
    if origin is not None:
        lines.append(f'Origin: {origin}')
    writer.write(('\r\n'.join(lines) + '\r\n\r\n').encode())
    await writer.drain()
    status = await asyncio.wait_for(reader.readline(), timeout=5.0)
    writer.close()
    return status.decode().strip()


# ---------------------------------------------------------------------------
#   Port selection
# ---------------------------------------------------------------------------

def test_auto_selects_next_free_port(tmp_path):
    """A busy base port makes the web server walk upward instead of failing."""
    async def scenario():
        base = _free_port()
        blocker = await _occupy(base)
        web = _make(tmp_path, base, scan_limit=50)
        try:
            await web.start()
            assert web.port > base
        finally:
            await web.stop()
            blocker.close()
            await blocker.wait_closed()

    asyncio.run(scenario())


def test_pinned_port_conflict_is_fatal(tmp_path):
    """scan_limit=1 (an explicitly named --web-port) must fail loudly."""
    async def scenario():
        base = _free_port()
        blocker = await _occupy(base)
        web = _make(tmp_path, base, scan_limit=1)
        try:
            with pytest.raises(OSError):
                await web.start()
        finally:
            blocker.close()
            await blocker.wait_closed()

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
#   Origin allow-list
# ---------------------------------------------------------------------------

def test_empty_allow_list_refuses_a_foreign_origin(tmp_path):
    """The default is same-origin only, not accept-anything.

    This is the configuration nobody configures, so it is the one that has
    to be safe: a public world with no origin list used to accept a socket
    from any page on the internet.
    """
    async def scenario():
        web = _make(tmp_path, _free_port())
        await web.start()
        try:
            status = await _upgrade_request(web.port, 'https://evil.example')
            assert '403' in status
        finally:
            await web.stop()

    asyncio.run(scenario())


def test_empty_allow_list_permits_its_own_origin(tmp_path):
    """The common case needs no configuration: client and socket, one host."""
    async def scenario():
        web = _make(tmp_path, _free_port())
        await web.start()
        try:
            status = await _upgrade_request(
                web.port, f'http://127.0.0.1:{web.port}')
            assert '101' in status
        finally:
            await web.stop()

    asyncio.run(scenario())


def test_same_origin_holds_when_a_proxy_terminates_tls(tmp_path):
    """Behind a proxy the page is https and this hop is not.

    The schemes legitimately differ, so only the authority halves may be
    compared -- comparing whole origins would reject the recommended
    deployment.
    """
    async def scenario():
        web = _make(tmp_path, _free_port())
        await web.start()
        try:
            status = await _upgrade_request(
                web.port, f'https://127.0.0.1:{web.port}')
            assert '101' in status
        finally:
            await web.stop()

    asyncio.run(scenario())


def test_star_restores_accept_anything(tmp_path):
    """An explicit opt-out for anyone who wants the old behaviour back."""
    async def scenario():
        web = _make(tmp_path, _free_port(), allowed_origins=['*'])
        await web.start()
        try:
            status = await _upgrade_request(web.port, 'https://evil.example')
            assert '101' in status
        finally:
            await web.stop()

    asyncio.run(scenario())


def test_a_listed_origin_is_allowed_alongside_same_origin(tmp_path):
    """The list adds origins; it does not replace the server's own."""
    async def scenario():
        web = _make(tmp_path, _free_port(),
                    allowed_origins=['https://play.example.com'])
        await web.start()
        try:
            listed = await _upgrade_request(web.port,
                                            'https://play.example.com')
            own = await _upgrade_request(web.port,
                                         f'http://127.0.0.1:{web.port}')
            assert '101' in listed and '101' in own
        finally:
            await web.stop()

    asyncio.run(scenario())


def test_disallowed_origin_is_refused(tmp_path):
    """Cross-site WebSocket hijacking: a page on another origin is refused."""
    async def scenario():
        web = _make(tmp_path, _free_port(),
                    allowed_origins=['https://play.example.com'])
        await web.start()
        try:
            status = await _upgrade_request(web.port, 'https://evil.example')
            assert '403' in status
        finally:
            await web.stop()

    asyncio.run(scenario())


def test_allowed_origin_passes(tmp_path):
    async def scenario():
        web = _make(tmp_path, _free_port(),
                    allowed_origins=['https://play.example.com'])
        await web.start()
        try:
            status = await _upgrade_request(web.port,
                                            'https://play.example.com')
            assert '101' in status
        finally:
            await web.stop()

    asyncio.run(scenario())


def test_web_host_defaults_to_the_game_host():
    """One knob served both listeners, so the client could not be hidden."""
    from moo.config import NetworkConfig
    assert NetworkConfig(host='0.0.0.0').effective_web_host == '0.0.0.0'


def test_web_host_moves_only_the_client():
    """The proxy case: client on loopback, game still answering publicly."""
    from moo.config import NetworkConfig
    net = NetworkConfig(host='0.0.0.0', web_host='127.0.0.1')
    assert net.effective_web_host == '127.0.0.1'
    assert net.host == '0.0.0.0'


def test_origin_list_accepts_comma_separated_string(tmp_path):
    """An environment variable delivers a string, not a list."""
    web = _make(tmp_path, 9999,
                allowed_origins='https://a.example, https://b.example/')
    assert web._allowed_origins == ['https://a.example', 'https://b.example']


def test_missing_origin_header_is_allowed(tmp_path):
    """Non-browser clients send no Origin and aren't the threat model."""
    async def scenario():
        web = _make(tmp_path, _free_port(),
                    allowed_origins=['https://play.example.com'])
        await web.start()
        try:
            status = await _upgrade_request(web.port, origin=None)
            assert '101' in status
        finally:
            await web.stop()

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
#   Static file serving
# ---------------------------------------------------------------------------

def test_serves_index_at_root(tmp_path):
    (tmp_path / 'index.html').write_text('<h1>MegaMOO</h1>')

    async def scenario():
        web = _make(tmp_path, _free_port())
        await web.start()
        try:
            reader, writer = await asyncio.open_connection(
                '127.0.0.1', web.port)
            writer.write(b'GET / HTTP/1.1\r\nHost: x\r\n\r\n')
            await writer.drain()
            body = await asyncio.wait_for(reader.read(-1), timeout=5.0)
            writer.close()
            assert b'200 OK' in body
            assert b'<h1>MegaMOO</h1>' in body
        finally:
            await web.stop()

    asyncio.run(scenario())


def test_static_requests_do_not_consume_the_session_budget(tmp_path):
    """Loading the client is several GETs; they must not block its socket.

    The rate limiter once counted every HTTP request, so index.html + CSS
    + two scripts spent four of five permits and the WebSocket upgrade
    that followed was refused -- the client could never connect at all.
    """
    (tmp_path / 'index.html').write_text('<h1>MegaMOO</h1>')

    async def scenario():
        web = _make(tmp_path, _free_port())
        await web.start()
        try:
            for _ in range(12):
                reader, writer = await asyncio.open_connection(
                    '127.0.0.1', web.port)
                writer.write(b'GET / HTTP/1.1\r\nHost: x\r\n\r\n')
                await writer.drain()
                await asyncio.wait_for(reader.read(-1), timeout=5.0)
                writer.close()
            status = await _upgrade_request(web.port)
            assert '101' in status
        finally:
            await web.stop()

    asyncio.run(scenario())


def test_rapid_sessions_are_rate_limited(tmp_path):
    """The limit still applies where it matters: repeated game sessions."""
    async def scenario():
        web = _make(tmp_path, _free_port())
        await web.start()
        try:
            results = [await _upgrade_request(web.port) for _ in range(7)]
            assert any('429' in r for r in results), \
                'session rate limiting is not applying to upgrades'
        finally:
            await web.stop()

    asyncio.run(scenario())


def test_directory_traversal_is_blocked(tmp_path):
    async def scenario():
        web = _make(tmp_path, _free_port())
        await web.start()
        try:
            reader, writer = await asyncio.open_connection(
                '127.0.0.1', web.port)
            writer.write(b'GET /../../etc/passwd HTTP/1.1\r\nHost: x\r\n\r\n')
            await writer.drain()
            body = await asyncio.wait_for(reader.read(-1), timeout=5.0)
            writer.close()
            assert b'403' in body
        finally:
            await web.stop()

    asyncio.run(scenario())
