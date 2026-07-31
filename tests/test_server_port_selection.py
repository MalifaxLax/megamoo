"""Unit tests for the game listener's port walk.

Exercises ``listen_walking_ports`` directly with real loopback sockets --
no database, no MegaMOOServer -- plus the config rule that decides how
many ports the walk is allowed to try.
"""
import asyncio
import errno

import pytest

from moo.config import ServerConfig
from moo.server import listen_walking_ports


async def _handle(reader, writer):
    writer.close()


def _free_port() -> int:
    """A port that was free a moment ago -- good enough as a scan base."""
    import socket
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


async def _occupy(port):
    """Hold `port` open so the walk has to look elsewhere."""
    return await asyncio.start_server(_handle, '127.0.0.1', port)


def test_uses_first_port_when_free():
    base = _free_port()

    async def _run():
        server, port = await listen_walking_ports(_handle, '127.0.0.1',
                                                  base, 50)
        try:
            assert port == base
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(_run())


def test_walks_past_a_busy_port():
    """A second database can boot without hand-picking a port."""
    base = _free_port()

    async def _run():
        blocker = await _occupy(base)
        try:
            server, port = await listen_walking_ports(_handle, '127.0.0.1',
                                                      base, 50)
            try:
                assert base < port <= base + 49
                # Genuinely listening on the port it reported.
                reader, writer = await asyncio.open_connection('127.0.0.1',
                                                               port)
                writer.close()
                await writer.wait_closed()
            finally:
                server.close()
                await server.wait_closed()
        finally:
            blocker.close()
            await blocker.wait_closed()

    asyncio.run(_run())


def test_scan_limit_of_one_pins_the_port():
    """A named port is a request for *that* port: a conflict is fatal."""
    base = _free_port()

    async def _run():
        blocker = await _occupy(base)
        try:
            with pytest.raises(OSError) as exc:
                await listen_walking_ports(_handle, '127.0.0.1', base, 1)
            assert f"port {base}" in str(exc.value)
        finally:
            blocker.close()
            await blocker.wait_closed()

    asyncio.run(_run())


def test_exhausted_scan_reports_the_whole_range():
    base = _free_port()

    async def _run():
        # Occupy the entire (tiny) scan range.
        blockers = []
        try:
            for port in range(base, base + 3):
                try:
                    blockers.append(await _occupy(port))
                except OSError:
                    pytest.skip('scan range not contiguously bindable')
            with pytest.raises(OSError) as exc:
                await listen_walking_ports(_handle, '127.0.0.1', base, 3)
            assert f"ports {base}-{base + 2}" in str(exc.value)
        finally:
            for b in blockers:
                b.close()
                await b.wait_closed()

    asyncio.run(_run())


def test_non_eaddrinuse_error_is_not_walked_past():
    """A bad host fails on the first try, not 50 identical times."""
    attempts = []

    async def _run():
        async def boom(handler, host, port, **kwargs):
            attempts.append(port)
            raise OSError(errno.EADDRNOTAVAIL, 'Cannot assign address')

        real = asyncio.start_server
        asyncio.start_server = boom
        try:
            with pytest.raises(OSError) as exc:
                await listen_walking_ports(_handle, '203.0.113.1', 6770, 50)
            assert exc.value.errno == errno.EADDRNOTAVAIL
        finally:
            asyncio.start_server = real

    asyncio.run(_run())
    assert attempts == [6770]


def test_walking_is_the_default():
    """Plain launches walk; only an explicit --port turns that off."""
    assert ServerConfig().network.auto_port is True


def test_port_scan_limit_is_validated():
    config = ServerConfig()
    config.network.port_scan_limit = 0
    with pytest.raises(ValueError, match='port_scan_limit'):
        config.validate()
