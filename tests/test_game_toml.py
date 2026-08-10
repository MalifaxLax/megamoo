"""megamoo.toml: the world's own statement of how it is served.

The file existed, said "what to serve, and where" in its own header, and
was read from exactly one place -- inside `_apply_dev_defaults`. So the
one launch that most needs its settings written down rather than retyped,
a production server, ignored it entirely. These cover the settings it can
now carry and the precedence between the file and a flag.

The 3.10 fallback parser is covered alongside the tomllib path, because
it is the one that only some machines ever run and so the one that rots.
"""
import argparse

import pytest

from moo import cli


FULL = """\
[game]
name = "Demo"
database = "world.db"
verbs = "verbs"

[server]
host = "0.0.0.0"
port = 7000
web = true
web_host = "127.0.0.1"
web_port = 8888
web_tls = false
tls_port = 6771
tls_cert = "certs/fullchain.pem"
tls_key = "certs/privkey.pem"
web_origins = ["https://play.example.com", "https://www.example.com"]
"""


def _args(**over):
    """An argparse namespace shaped like a launch with nothing passed."""
    ns = argparse.Namespace(
        database=None, host=None, port=None, web=False, web_host=None,
        web_port=None, web_origins=None, web_tls=False, tls_port=None,
        tls_cert=None, tls_key=None,
    )
    for k, v in over.items():
        setattr(ns, k, v)
    return ns


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A directory holding a megamoo.toml, and cwd pointed at it."""
    def write(text):
        (tmp_path / 'megamoo.toml').write_text(text)
        monkeypatch.chdir(tmp_path)
        return tmp_path
    return write


# ---------------------------------------------------------------------------
#   Reading
# ---------------------------------------------------------------------------

def test_every_server_key_is_read(world):
    world(FULL)
    got = cli._read_game_toml()
    assert got['host'] == '0.0.0.0'
    assert got['port'] == 7000
    assert got['web'] is True
    assert got['web_host'] == '127.0.0.1'
    assert got['web_port'] == 8888
    assert got['tls_port'] == 6771
    assert got['tls_cert'] == 'certs/fullchain.pem'
    assert got['tls_key'] == 'certs/privkey.pem'


def test_origins_normalise_to_the_comma_separated_shape(world):
    """A TOML array in, the string every other CLI path speaks out."""
    world(FULL)
    assert cli._read_game_toml()['web_origins'] == (
        'https://play.example.com,https://www.example.com')


def test_origins_may_also_be_written_as_a_plain_string(world):
    """What somebody writes on the first try, before reading anything."""
    world('[server]\nweb_origins = "https://a.example, https://b.example"\n')
    assert cli._read_game_toml()['web_origins'] == (
        'https://a.example,https://b.example')


def test_a_missing_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli._read_game_toml() == {}


def test_a_wrongly_typed_value_is_ignored_rather_than_crashing(world):
    """A port written as a string should not take the server down."""
    world('[server]\nport = "7000"\nweb_host = "127.0.0.1"\n')
    got = cli._read_game_toml()
    assert 'port' not in got
    assert got['web_host'] == '127.0.0.1'


def test_unknown_keys_are_ignored(world):
    world('[server]\nport = 7000\nnonsense = "x"\n')
    assert 'nonsense' not in cli._read_game_toml()


# ---------------------------------------------------------------------------
#   The 3.10 fallback parser
# ---------------------------------------------------------------------------

def _without_tomllib(monkeypatch):
    """Make `import tomllib` raise, as it does on 3.10."""
    real_import = __import__

    def fake(name, *a, **kw):
        if name == 'tomllib':
            raise ImportError('no tomllib')
        return real_import(name, *a, **kw)

    monkeypatch.setattr('builtins.__import__', fake)


def test_the_fallback_parser_reads_the_same_settings(world, monkeypatch):
    world(FULL)
    _without_tomllib(monkeypatch)
    got = cli._read_game_toml()
    assert got['port'] == 7000
    assert got['web'] is True
    assert got['web_host'] == '127.0.0.1'
    assert got['tls_cert'] == 'certs/fullchain.pem'
    assert got['web_origins'] == (
        'https://play.example.com,https://www.example.com')


def test_the_fallback_parser_agrees_with_tomllib(world, monkeypatch):
    """Two parsers for one file is two chances to disagree."""
    world(FULL)
    with_lib = cli._read_game_toml()
    _without_tomllib(monkeypatch)
    assert cli._read_game_toml() == with_lib


def test_the_fallback_parser_still_ignores_comments(world, monkeypatch):
    world('[server]\nport = 7000  # the port\n')
    _without_tomllib(monkeypatch)
    assert cli._read_game_toml()['port'] == 7000


# ---------------------------------------------------------------------------
#   Applying, and precedence
# ---------------------------------------------------------------------------

def test_the_file_fills_in_what_the_command_line_left_unset(world):
    world(FULL)
    args = _args()
    cli._apply_game_toml(args)
    assert args.database == 'world.db'
    assert args.port == 7000
    assert args.web_host == '127.0.0.1'
    assert args.web is True


def test_a_flag_beats_the_file(world):
    """The file is the standing instruction; a flag is the specific one."""
    world(FULL)
    args = _args(port=9999, web_host='0.0.0.0', database='other.db')
    cli._apply_game_toml(args)
    assert args.port == 9999
    assert args.web_host == '0.0.0.0'
    assert args.database == 'other.db'


def test_a_world_without_the_file_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = _args()
    cli._apply_game_toml(args)
    assert args.port is None and args.web is False and args.database is None
