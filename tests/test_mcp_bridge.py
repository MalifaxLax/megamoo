"""Unit tests for the MCP bridge's log reading (no server needed)."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))

import megamoo_mcp


def test_default_log_path_is_repo_root():
    assert megamoo_mcp.LOG_PATH.name == 'megamoo.log'
    assert megamoo_mcp.LOG_PATH.parent.name != 'tools'


def test_tail_log_reads_last_lines(tmp_path, monkeypatch):
    log = tmp_path / 'megamoo.log'
    log.write_text('\n'.join(f'line {i}' for i in range(100)) + '\n')
    monkeypatch.setattr(megamoo_mcp, 'LOG_PATH', log)
    out = megamoo_mcp.tail_log_impl(lines=5)
    assert out.splitlines() == [f'line {i}' for i in range(95, 100)]


def test_tail_log_filter(tmp_path, monkeypatch):
    log = tmp_path / 'megamoo.log'
    log.write_text('INFO boot\nERROR bad thing\nINFO fine\n')
    monkeypatch.setattr(megamoo_mcp, 'LOG_PATH', log)
    out = megamoo_mcp.tail_log_impl(lines=50, filter='ERROR')
    assert out == 'ERROR bad thing'


def test_tail_log_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(megamoo_mcp, 'LOG_PATH', tmp_path / 'nope.log')
    out = megamoo_mcp.tail_log_impl()
    assert 'not found' in out.lower()


# ---------------------------------------------------------------------------
#   ApiClient unit tests — tiny in-test TCP servers on port 0 / loopback
# ---------------------------------------------------------------------------

def test_auth_failure_resets_connection(monkeypatch):
    """Bug 1: failed auth must _reset() so the next call can reconnect."""

    async def _run():
        # Fake server: reply auth-failed to the first line, then close.
        async def handle(reader, writer):
            await reader.readline()          # consume the auth request
            writer.write(
                json.dumps({'id': 1, 'ok': False,
                            'error': 'Invalid auth token'}).encode() + b'\n')
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            client = megamoo_mcp.ApiClient()
            monkeypatch.setattr(megamoo_mcp, 'API_HOST', '127.0.0.1')
            monkeypatch.setattr(megamoo_mcp, 'API_PORT', port)
            try:
                await client.call('anything')
                assert False, "Expected RuntimeError"
            except RuntimeError as e:
                assert 'MEGAMOO_API_TOKEN' in str(e)
            assert client._writer is None   # wedge bug: must be reset

    asyncio.run(_run())


def test_response_id_mismatch_raises_unreachable(monkeypatch):
    """Bug 2: wrong response id must surface as RuntimeError (unreachable)."""

    async def _run():
        # Fake server: auth OK, then reply with a mismatched id.
        async def handle(reader, writer):
            await reader.readline()          # auth request (id=1)
            writer.write(
                json.dumps({'id': 1, 'ok': True, 'result': {}}).encode() + b'\n')
            await writer.drain()
            await reader.readline()          # tool request (id=2)
            writer.write(
                json.dumps({'id': 99, 'ok': True, 'result': {}}).encode() + b'\n')
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            client = megamoo_mcp.ApiClient()
            monkeypatch.setattr(megamoo_mcp, 'API_HOST', '127.0.0.1')
            monkeypatch.setattr(megamoo_mcp, 'API_PORT', port)
            try:
                await client.call('get_object', {'objnum': 1})
                assert False, "Expected RuntimeError"
            except RuntimeError as e:
                # ConnectionError(id mismatch) is an OSError subclass →
                # caught by except (OSError, json.JSONDecodeError) → UNREACHABLE
                assert 'unreachable' in str(e).lower() or 'not running' in str(e).lower()
            assert client._writer is None   # must be reset after desync

    asyncio.run(_run())
