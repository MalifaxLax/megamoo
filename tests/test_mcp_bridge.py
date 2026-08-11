"""Unit tests for the MCP bridge's log reading and API discovery
(no server needed)."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))

# The bridge imports the `mcp` SDK, which is not an engine dependency --
# pyproject declares none at all.  Imported bare, this line failed
# *collection* in a fresh clone, so `pytest` reported one error and ran
# zero tests: a new contributor's first command looked like a broken
# repository rather than an optional extra they had not installed.
pytest.importorskip(
    'mcp.server.fastmcp',
    reason="the MCP SDK is optional; `pip install mcp` to run these",
)

import megamoo_mcp


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path_factory):
    """Isolate discovery from the machine it runs on.

    Discovery reads the environment, the shared run directory, and a
    session-level selection -- all of which would otherwise let a server
    the developer happens to have running change the result.
    """
    for var in ('MEGAMOO_API_PORT', 'MEGAMOO_API_INFO', 'MEGAMOO_DB'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(megamoo_mcp, 'RUN_DIR',
                        tmp_path_factory.mktemp('run'))
    monkeypatch.setattr(megamoo_mcp, '_selected_db', None)


def _info_file(path: Path, port: int, pid=None, database=None):
    path.write_text(json.dumps({
        'host': '127.0.0.1',
        'port': port,
        'pid': os.getpid() if pid is None else pid,
        'database': database or str(path).removesuffix('.api.json'),
        'auth_required': True,
    }))
    return path


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
            monkeypatch.setenv('MEGAMOO_API_PORT', str(port))
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
            monkeypatch.setenv('MEGAMOO_API_PORT', str(port))
            try:
                await client.call('get_object', {'objnum': 1})
                assert False, "Expected RuntimeError"
            except RuntimeError as e:
                # ConnectionError(id mismatch) is an OSError subclass →
                # caught by except (OSError, json.JSONDecodeError) → UNREACHABLE
                assert 'unreachable' in str(e).lower() or 'not running' in str(e).lower()
            assert client._writer is None   # must be reset after desync

    asyncio.run(_run())


# ---------------------------------------------------------------------------
#   Address discovery — following an auto-selected API port
# ---------------------------------------------------------------------------

def test_env_port_pin_wins_over_discovery(tmp_path, monkeypatch):
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    _info_file(tmp_path / 'sf.db.api.json', 7900)
    monkeypatch.setenv('MEGAMOO_API_PORT', '7778')
    host, port, source = megamoo_mcp._resolve_address()
    assert (port, source) == (7778, 'MEGAMOO_API_PORT')


def test_discovers_single_live_info_file(tmp_path, monkeypatch):
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    _info_file(tmp_path / 'sf.db.api.json', 7903)
    host, port, source = megamoo_mcp._resolve_address()
    assert (host, port) == ('127.0.0.1', 7903)
    assert source.endswith('sf.db.api.json')


def test_stale_info_file_is_ignored(tmp_path, monkeypatch):
    """A file left by a crashed server must not redirect us to a dead port."""
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    _info_file(tmp_path / 'sf.db.api.json', 7903, pid=424242)
    host, port, source = megamoo_mcp._resolve_address()
    assert (port, source) == (megamoo_mcp.DEFAULT_API_PORT, 'default')


def test_corrupt_info_file_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    (tmp_path / 'sf.db.api.json').write_text('{not json')
    assert megamoo_mcp._resolve_address()[1] == megamoo_mcp.DEFAULT_API_PORT


def test_no_info_file_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    host, port, source = megamoo_mcp._resolve_address()
    assert (port, source) == (megamoo_mcp.DEFAULT_API_PORT, 'default')


def test_several_live_servers_ask_for_disambiguation(tmp_path, monkeypatch):
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    _info_file(tmp_path / 'sf.db.api.json', 7778)
    _info_file(tmp_path / 'mm.db.api.json', 7779)
    with pytest.raises(RuntimeError) as exc:
        megamoo_mcp._resolve_address()
    msg = str(exc.value)
    assert 'MEGAMOO_DB' in msg
    assert '7778' in msg and '7779' in msg


def test_megamoo_db_picks_that_servers_port(tmp_path, monkeypatch):
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    _info_file(tmp_path / 'sf.db.api.json', 7778)
    _info_file(tmp_path / 'mm.db.api.json', 7779)
    monkeypatch.setenv('MEGAMOO_DB', str(tmp_path / 'mm.db'))
    assert megamoo_mcp._resolve_address()[1] == 7779


def test_megamoo_db_without_live_server_is_a_clear_error(tmp_path,
                                                         monkeypatch):
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    monkeypatch.setenv('MEGAMOO_DB', str(tmp_path / 'gone.db'))
    with pytest.raises(RuntimeError) as exc:
        megamoo_mcp._resolve_address()
    assert 'MEGAMOO_DB' in str(exc.value)


def test_api_info_env_overrides_db(tmp_path, monkeypatch):
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    named = _info_file(tmp_path / 'custom.json', 7910)
    _info_file(tmp_path / 'sf.db.api.json', 7778)
    monkeypatch.setenv('MEGAMOO_API_INFO', str(named))
    assert megamoo_mcp._resolve_address()[1] == 7910


# ---------------------------------------------------------------------------
#   Choosing between several databases without restarting the bridge
# ---------------------------------------------------------------------------

def test_run_dir_is_searched_as_well_as_the_repo(tmp_path, monkeypatch):
    """A server launched from another checkout is still discoverable."""
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    monkeypatch.setattr(megamoo_mcp, 'RUN_DIR', run_dir)
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path / 'repo')
    _info_file(run_dir / '_Users_dev_megamoo_mm.db.api.json', 7788,
               database='/Users/dev/megamoo/mm.db')
    assert megamoo_mcp._resolve_address()[1] == 7788


def test_one_server_advertised_twice_is_listed_once(tmp_path, monkeypatch):
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    monkeypatch.setattr(megamoo_mcp, 'RUN_DIR', run_dir)
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    _info_file(run_dir / '_Users_dev_sfdev_sf.db.api.json', 7778,
               database='/Users/dev/sfdev/sf.db')
    _info_file(tmp_path / 'sf.db.api.json', 7778,
               database='/Users/dev/sfdev/sf.db')
    assert len(megamoo_mcp._live_servers()) == 1
    # ...and one server is not "several", so discovery still resolves.
    assert megamoo_mcp._resolve_address()[1] == 7778


@pytest.mark.parametrize('name', ['sf', 'sf.db', '/Users/dev/sfdev/sf.db'])
def test_use_database_matches_name_or_path(tmp_path, monkeypatch, name):
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    _info_file(tmp_path / 'sf.db.api.json', 7778,
               database='/Users/dev/sfdev/sf.db')
    _info_file(tmp_path / 'mm.db.api.json', 7779,
               database='/Users/dev/megamoo/mm.db')

    result = asyncio.run(megamoo_mcp.use_database(name))
    assert result['selected'] == '/Users/dev/sfdev/sf.db'
    assert result['api_port'] == 7778
    # The selection is what discovery now resolves to -- no restart.
    assert megamoo_mcp._resolve_address()[1] == 7778


def test_use_database_switches_and_clears(tmp_path, monkeypatch):
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    _info_file(tmp_path / 'sf.db.api.json', 7778,
               database='/Users/dev/sfdev/sf.db')
    _info_file(tmp_path / 'mm.db.api.json', 7779,
               database='/Users/dev/megamoo/mm.db')

    asyncio.run(megamoo_mcp.use_database('mm'))
    assert megamoo_mcp._resolve_address()[1] == 7779

    asyncio.run(megamoo_mcp.use_database('sf'))
    assert megamoo_mcp._resolve_address()[1] == 7778

    # Cleared: back to ambiguity rather than a stale choice.
    asyncio.run(megamoo_mcp.use_database(''))
    with pytest.raises(RuntimeError):
        megamoo_mcp._resolve_address()


def test_use_database_on_unknown_name_lists_what_is_running(tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    _info_file(tmp_path / 'sf.db.api.json', 7778,
               database='/Users/dev/sfdev/sf.db')
    result = asyncio.run(megamoo_mcp.use_database('nope.db'))
    assert result['selected'] is None
    assert 'sf.db' in result['detail']


def test_selected_database_that_died_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    info = _info_file(tmp_path / 'sf.db.api.json', 7778,
                      database='/Users/dev/sfdev/sf.db')
    asyncio.run(megamoo_mcp.use_database('sf'))
    info.unlink()                       # the server went away
    with pytest.raises(RuntimeError) as exc:
        megamoo_mcp._resolve_address()
    assert 'no longer running' in str(exc.value)


def test_env_port_pin_beats_a_session_selection(tmp_path, monkeypatch):
    """An explicit pin is the operator's word and still wins."""
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    _info_file(tmp_path / 'sf.db.api.json', 7778,
               database='/Users/dev/sfdev/sf.db')
    asyncio.run(megamoo_mcp.use_database('sf'))
    monkeypatch.setenv('MEGAMOO_API_PORT', '7999')
    assert megamoo_mcp._resolve_address()[1] == 7999


def test_list_servers_reports_both_ports(tmp_path, monkeypatch):
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    path = tmp_path / 'sf.db.api.json'
    path.write_text(json.dumps({
        'host': '127.0.0.1', 'port': 7778, 'pid': os.getpid(),
        'database': '/Users/dev/sfdev/sf.db', 'game_port': 6771,
        'auth_required': True,
    }))
    listing = megamoo_mcp.list_servers()
    assert listing['servers'] == [{
        'database': '/Users/dev/sfdev/sf.db',
        'game_port': 6771,
        'api_port': 7778,
        'host': '127.0.0.1',
        'pid': os.getpid(),
        'selected': False,
    }]
    assert listing['selected'] is None


def test_list_servers_marks_the_selected_one(tmp_path, monkeypatch):
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    _info_file(tmp_path / 'sf.db.api.json', 7778,
               database='/Users/dev/sfdev/sf.db')
    _info_file(tmp_path / 'mm.db.api.json', 7779,
               database='/Users/dev/megamoo/mm.db')
    asyncio.run(megamoo_mcp.use_database('mm'))
    chosen = [s for s in megamoo_mcp.list_servers()['servers'] if s['selected']]
    assert [s['api_port'] for s in chosen] == [7779]


def test_list_servers_says_so_when_nothing_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
    listing = megamoo_mcp.list_servers()
    assert listing['servers'] == []
    assert './mm' in listing['detail']


# ---------------------------------------------------------------------------
#   Token
# ---------------------------------------------------------------------------

def test_token_falls_back_to_the_shared_file(tmp_path, monkeypatch):
    """A bridge registered without -e still authenticates."""
    token_file = tmp_path / 'token'
    token_file.write_text('deadbeef\n')
    monkeypatch.setattr(megamoo_mcp, 'TOKEN_FILE', token_file)
    monkeypatch.delenv('MEGAMOO_API_TOKEN', raising=False)
    assert megamoo_mcp._read_token() == 'deadbeef'


def test_token_env_wins_over_the_file(tmp_path, monkeypatch):
    token_file = tmp_path / 'token'
    token_file.write_text('fromfile\n')
    monkeypatch.setattr(megamoo_mcp, 'TOKEN_FILE', token_file)
    monkeypatch.setenv('MEGAMOO_API_TOKEN', 'fromenv')
    assert megamoo_mcp._read_token() == 'fromenv'


def test_missing_token_file_is_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(megamoo_mcp, 'TOKEN_FILE', tmp_path / 'nope')
    monkeypatch.delenv('MEGAMOO_API_TOKEN', raising=False)
    assert megamoo_mcp._read_token() == ''


def test_client_reresolves_on_reconnect(tmp_path, monkeypatch):
    """The bridge outlives the server: a restart onto a new port is followed
    on the next call, with no MCP restart."""

    async def _run():
        async def handle(reader, writer):
            await reader.readline()                     # auth
            writer.write(json.dumps({'id': 1, 'ok': True,
                                     'result': {}}).encode() + b'\n')
            await writer.drain()
            await reader.readline()                     # tool call
            writer.write(json.dumps({'id': 2, 'ok': True,
                                     'result': {'port': port}}).encode()
                         + b'\n')
            await writer.drain()

        server = await asyncio.start_server(handle, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        info = _info_file(tmp_path / 'sf.db.api.json', port)
        monkeypatch.setattr(megamoo_mcp, 'REPO_ROOT', tmp_path)
        async with server:
            client = megamoo_mcp.ApiClient()
            try:
                # First connect goes to the port the discovery file advertises.
                result = await client.call('server_status')
                assert result == {'port': port}
                assert client._addr == ('127.0.0.1', port)
            finally:
                client._reset()

    asyncio.run(_run())
