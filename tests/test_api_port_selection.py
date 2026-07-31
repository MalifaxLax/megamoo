"""Unit tests for API port auto-selection and the discovery file.

No game server involved: an ApiServer is started directly against a stub
database, with real sockets on loopback.
"""
import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from moo.api import ApiServer


@dataclass
class Cfg:
    """Stand-in for moo.config.ApiConfig."""
    port: int
    auto_port: bool = True
    port_scan_limit: int = 50
    info_path: str = ''
    host: str = '127.0.0.1'
    auth_token: str = ''
    testbot_objnum: int = 0


class StubDatabase:
    def __init__(self, path):
        self.path = Path(path)


def _free_port() -> int:
    """A port that was free a moment ago -- good enough as a scan base."""
    import socket
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


async def _occupy(port):
    """Hold `port` open so the API has to look elsewhere."""
    async def handle(reader, writer):
        writer.close()
    return await asyncio.start_server(handle, '127.0.0.1', port)


def test_auto_selects_next_free_port(tmp_path):
    """A busy base port makes the API walk upward instead of failing."""
    base = _free_port()

    async def _run():
        blocker = await _occupy(base)
        api = ApiServer(StubDatabase(tmp_path / 'game.db'), Cfg(port=base))
        try:
            await api.start()
            assert api.port != base
            assert base < api.port <= base + 49
            # And it is genuinely listening there.
            reader, writer = await asyncio.open_connection('127.0.0.1',
                                                           api.port)
            writer.close()
            await writer.wait_closed()
        finally:
            await api.stop()
            blocker.close()
            await blocker.wait_closed()

    asyncio.run(_run())


def test_uses_configured_port_when_free(tmp_path):
    base = _free_port()

    async def _run():
        api = ApiServer(StubDatabase(tmp_path / 'game.db'), Cfg(port=base))
        try:
            await api.start()
            assert api.port == base
        finally:
            await api.stop()

    asyncio.run(_run())


def test_pinned_port_fails_loudly_when_busy(tmp_path):
    """--api-port means *that* port: a conflict must not be papered over."""
    base = _free_port()

    async def _run():
        blocker = await _occupy(base)
        api = ApiServer(StubDatabase(tmp_path / 'game.db'),
                        Cfg(port=base, auto_port=False))
        try:
            with pytest.raises(OSError) as exc:
                await api.start()
            assert str(base) in str(exc.value)
            assert 'in use' in str(exc.value)
        finally:
            blocker.close()
            await blocker.wait_closed()

    asyncio.run(_run())


def test_scan_limit_is_honoured(tmp_path):
    """Exhausting the scan window is an error, not an endless climb."""
    base = _free_port()

    async def _run():
        blockers = [await _occupy(base + i) for i in range(3)]
        api = ApiServer(StubDatabase(tmp_path / 'game.db'),
                        Cfg(port=base, port_scan_limit=3))
        try:
            with pytest.raises(OSError):
                await api.start()
        finally:
            for b in blockers:
                b.close()
                await b.wait_closed()

    asyncio.run(_run())


def test_discovery_file_records_actual_port(tmp_path):
    """The advertised port is the one bound, not the one requested."""
    base = _free_port()
    db = tmp_path / 'game.db'
    info_file = Path(str(db) + '.api.json')

    async def _run():
        blocker = await _occupy(base)
        api = ApiServer(StubDatabase(db), Cfg(port=base, auth_token='t'))
        try:
            await api.start()
            info = json.loads(info_file.read_text())
            assert info['port'] == api.port != base
            assert info['host'] == '127.0.0.1'
            assert info['pid'] == os.getpid()
            assert info['database'] == str(db)
            assert info['auth_required'] is True
        finally:
            await api.stop()
            blocker.close()
            await blocker.wait_closed()
        assert not info_file.exists(), 'stop() should clean up after itself'

    asyncio.run(_run())


def test_discovery_file_can_be_disabled(tmp_path):
    db = tmp_path / 'game.db'

    async def _run():
        api = ApiServer(StubDatabase(db),
                        Cfg(port=_free_port(), info_path='-'))
        try:
            await api.start()
            assert not Path(str(db) + '.api.json').exists()
        finally:
            await api.stop()

    asyncio.run(_run())


def test_discovery_file_honours_explicit_path(tmp_path):
    target = tmp_path / 'elsewhere' / 'api.json'
    target.parent.mkdir()

    async def _run():
        api = ApiServer(StubDatabase(tmp_path / 'game.db'),
                        Cfg(port=_free_port(), info_path=str(target)))
        try:
            await api.start()
            assert json.loads(target.read_text())['port'] == api.port
        finally:
            await api.stop()

    asyncio.run(_run())


def test_stop_leaves_another_processs_file_alone(tmp_path):
    """A restarted server owns the file; our shutdown must not delete it."""
    db = tmp_path / 'game.db'
    info_file = Path(str(db) + '.api.json')

    async def _run():
        api = ApiServer(StubDatabase(db), Cfg(port=_free_port()))
        await api.start()
        # Simulate a successor process having rewritten the file.
        info_file.write_text(json.dumps({'host': '127.0.0.1',
                                         'port': 9999, 'pid': 424242}))
        await api.stop()
        assert info_file.exists()
        assert json.loads(info_file.read_text())['pid'] == 424242

    asyncio.run(_run())
