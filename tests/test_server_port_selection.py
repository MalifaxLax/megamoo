"""Unit tests for the game listener's port walk.

Exercises ``listen_walking_ports`` directly with real loopback sockets --
no database, no MegaMOOServer -- plus the config rule that decides how
many ports the walk is allowed to try, and the CLI path that decides
whether the walk is allowed at all.

That last part is where this went wrong once: every test below the socket
work passed while a plain ``megamoo --dev`` still refused to walk, because
they all asserted the *default* and none of them asserted what the command
line actually did with it.
"""
import asyncio
import errno
import inspect
import os
import subprocess
import sys
import textwrap

import pytest

from moo.config import ServerConfig
from moo.server import listen_walking_ports, run_server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


# ------------------------------------------------------------------
# Where a port came from
# ------------------------------------------------------------------
#
# `megamoo init` writes `[server] port = 6770` into every world it
# creates.  Once `_apply_game_toml` has folded that into `args`, it is
# indistinguishable from a typed `--port 6770` -- and `run_server` used
# to treat both as "the operator named a port", pin the listener, and
# fail.  So a first run on a machine where anything already held 6770
# ended in a traceback, for a port the operator had never chosen.


def _apply_toml(tmp_path, toml_body, argv_port=None):
    """Run `_apply_game_toml` in *tmp_path* and report what it filled in.

    Out of process because importing `moo.cli` opens `megamoo.log` in the
    working directory, which is the same reason `test_cli_logging` shells
    out.
    """
    (tmp_path / 'megamoo.toml').write_text(textwrap.dedent(toml_body))
    snippet = textwrap.dedent(f"""
        import argparse, json
        from moo.cli import _apply_game_toml
        args = argparse.Namespace(database=None, web=False, web_tls=False,
                                  port={argv_port!r})
        _apply_game_toml(args)
        print(json.dumps({{'port': args.port,
                          'from_toml': sorted(args.from_toml)}}))
    """)
    proc = subprocess.run([sys.executable, '-c', snippet],
                          cwd=tmp_path, capture_output=True, text=True,
                          env={**os.environ, 'PYTHONPATH': ROOT})
    assert proc.returncode == 0, proc.stderr
    import json
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_toml_port_is_recorded_as_file_sourced(tmp_path):
    """The file supplied it, so it is a preference and not an instruction."""
    out = _apply_toml(tmp_path, """
        [server]
        port = 6770
    """)
    assert out['port'] == 6770
    assert 'port' in out['from_toml']


def test_a_flag_port_is_not_recorded_as_file_sourced(tmp_path):
    """A typed --port wins, and is still recognisable as typed."""
    out = _apply_toml(tmp_path, """
        [server]
        port = 6770
    """, argv_port=7000)
    assert out['port'] == 7000, 'the flag must win over the file'
    assert 'port' not in out['from_toml']


def test_from_toml_exists_even_without_a_toml(tmp_path):
    """The attribute is unconditional; the early return must not skip it."""
    snippet = textwrap.dedent("""
        import argparse
        from moo.cli import _apply_game_toml
        args = argparse.Namespace(database=None, web=False, web_tls=False,
                                  port=None)
        _apply_game_toml(args)
        print(sorted(args.from_toml))
    """)
    proc = subprocess.run([sys.executable, '-c', snippet],
                          cwd=tmp_path, capture_output=True, text=True,
                          env={**os.environ, 'PYTHONPATH': ROOT})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == '[]'


# ------------------------------------------------------------------
# What run_server does with that
# ------------------------------------------------------------------


def test_run_server_takes_pin_port_and_defaults_to_pinning():
    """Callers that predate the parameter keep the old, pinning behaviour."""
    sig = inspect.signature(run_server)
    assert 'pin_port' in sig.parameters
    assert sig.parameters['pin_port'].default is True


def test_pinning_is_conditional_on_pin_port():
    """The pin must be guarded, not unconditional on a truthy port."""
    src = inspect.getsource(run_server)
    head, _, tail = src.partition('config.network.port = port')
    assert tail, 'the port override moved; this guard needs rewriting'
    # The auto_port kill must sit behind a pin_port check, not run flat.
    assert 'if pin_port:' in tail.split('if host:')[0], \
        'a toml-supplied port would pin the listener again'


def test_cli_tells_run_server_where_the_port_came_from():
    """The wiring, not just the capability -- this is what regressed."""
    import moo.cli
    src = inspect.getsource(moo.cli)
    assert 'pin_port=' in src, 'cli must pass pin_port'
    assert "'port' not in getattr(args, 'from_toml'" in src, \
        'cli must decide pin_port from where the port came'


# ------------------------------------------------------------------
# The parser itself
# ------------------------------------------------------------------
#
# Everything above reaches `args` by building an `argparse.Namespace` by
# hand, so argparse never runs.  That left the front door untested: the
# `port` positional shared a dest with `--port` and carried
# `default=argparse.SUPPRESS` to stop an absent positional clobbering the
# flag -- but SUPPRESS is the string '==SUPPRESS==', and argparse feeds a
# string default through `type` for an absent nargs='?' positional.  With
# `type=int` that is int('==SUPPRESS=='), so every launch that named no
# positional port died in the parser:
#
#     megamoo: error: argument port: invalid int value: '==SUPPRESS=='
#
# `megamoo --dev` and `megamoo world.db` are both that launch, and so is
# the second line of the README quick start.  Python 3.13 stopped
# converting string defaults and hid it; 3.10, 3.11 and 3.12 are supported
# and did not.  These tests run the real parser on real argv.


def _parse(tmp_path, argv, toml_body=None):
    """Run `MegaMOO.parse_arguments` on *argv* and report what it produced.

    Out of process for the same reason as `_apply_toml`: importing
    `moo.cli` opens `megamoo.log` in the working directory.
    """
    (tmp_path / 'world.db').write_bytes(b'')
    if toml_body is not None:
        (tmp_path / 'megamoo.toml').write_text(textwrap.dedent(toml_body))
    snippet = textwrap.dedent(f"""
        import json, sys
        sys.argv = ['megamoo'] + {argv!r}
        from moo.cli import MegaMOO
        args = MegaMOO().parse_arguments()
        print('RESULT' + json.dumps({{'port': args.port,
                                      'database': args.database,
                                      'new_database': args.new_database,
                                      'host': args.host,
                                      'from_toml': sorted(args.from_toml)}}))
    """)
    proc = subprocess.run([sys.executable, '-c', snippet],
                          cwd=tmp_path, capture_output=True, text=True,
                          env={**os.environ, 'PYTHONPATH': ROOT})
    assert proc.returncode == 0, (
        f'megamoo {" ".join(argv)} did not parse:\n{proc.stderr}')
    line = [l for l in proc.stdout.splitlines() if l.startswith('RESULT')]
    assert line, f'no result from {argv}:\n{proc.stdout}\n{proc.stderr}'
    import json
    return json.loads(line[-1][len('RESULT'):])


@pytest.mark.parametrize('argv', [
    ['world.db'],
    ['--dev'],
    ['--input', 'world.db'],
    ['world.db', '--port', '7777'],
    ['world.db', '--web'],
])
def test_a_launch_without_a_positional_port_parses(tmp_path, argv):
    """The absent positional must not be handed to `type` as a default."""
    out = _parse(tmp_path, argv)
    assert out['database'], f'megamoo {" ".join(argv)} lost the database'


def test_the_quick_start_second_line_parses(tmp_path):
    """`megamoo --dev` is what the README tells a new user to type."""
    assert _parse(tmp_path, ['--dev'])['database']


def test_a_positional_port_still_reaches_args_port(tmp_path):
    """The LambdaMOO spelling: <database> <new_database> <port>."""
    out = _parse(tmp_path, ['world.db', 'new.db', '7777'])
    assert out['port'] == 7777
    assert out['new_database'] == 'new.db'


def test_a_bare_positional_port_is_read_as_a_port(tmp_path):
    """`megamoo world.db 6770` -- the second positional is a port, not a db."""
    out = _parse(tmp_path, ['world.db', '6770'])
    assert out['port'] == 6770
    assert out['new_database'] is None


def test_a_positional_host_and_port_both_land(tmp_path):
    """`megamoo world.db localhost 6770` -- documented in the epilog."""
    out = _parse(tmp_path, ['world.db', 'localhost', '6770'])
    assert out['host'] == 'localhost'
    assert out['port'] == 6770


def test_an_absent_positional_does_not_clobber_the_flag(tmp_path):
    """What SUPPRESS was there to prevent, asserted directly this time."""
    assert _parse(tmp_path, ['world.db', '--port', '7777'])['port'] == 7777


def test_the_flag_wins_over_a_positional_port(tmp_path):
    """Both spellings given: the flag is the more specific instruction."""
    out = _parse(tmp_path, ['world.db', 'new.db', '7777', '--port', '8888'])
    assert out['port'] == 8888


def test_no_port_anywhere_leaves_it_none_for_the_toml(tmp_path):
    """`_apply_game_toml` fills only what is still None -- keep it None."""
    assert _parse(tmp_path, ['world.db'])['port'] is None


def test_a_toml_port_survives_the_parser(tmp_path):
    """The file is the standing preference when no spelling overrides it."""
    out = _parse(tmp_path, ['world.db'], toml_body="""
        [server]
        port = 6890
    """)
    assert out['port'] == 6890


def test_a_positional_port_beats_the_toml(tmp_path):
    """The merge must precede `_apply_game_toml`, which fills only None."""
    out = _parse(tmp_path, ['world.db', 'new.db', '7777'], toml_body="""
        [server]
        port = 6890
    """)
    assert out['port'] == 7777, 'a typed positional port must beat the file'
    assert 'port' not in out['from_toml'], \
        'a typed port must not be recorded as file-sourced, or it goes unpinned'
