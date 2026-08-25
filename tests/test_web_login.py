"""tests/test_web_login.py — web login must match the telnet login's rules.

The two transports run the same LoginHandler but finalise the session
separately, and they drifted: the web path had no ``handler.reconnect``
check, so a session takeover yanked the character out of the world into
the OOC login room *and* overwrote the ``last_location`` that puppet()
uses to put an IC character back. Every later trip through the game
portal then dropped them in the lobby.
"""
import asyncio
import types

import pytest

import moo.login
from moo.database import Database
# Not `from moo.globals import LOGIN_ROOM` any more: where a player lands is
# the world's decision, held on $globals.login_room, not the engine's.  The
# fixture therefore has to say where it is -- which is the behaviour under
# test, so saying it here is the point rather than a workaround.
LOGIN_ROOM = 14
from moo.objects import ObjectFlags
from moo.web.connection import WebSocketConnection


class FakeWriter:
    def get_extra_info(self, _name):
        return ('127.0.0.1', 5000)

    def write(self, _data):
        pass

    async def drain(self):
        pass

    def close(self):
        pass


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / 'weblogin.db'), mode='create')
    database.load()
    yield database
    database.close()


@pytest.fixture
def server(db):
    return types.SimpleNamespace(
        database=db,
        config=types.SimpleNamespace(),
        loop=None,
    )


def _make_world(db):
    """A login room, an elsewhere room, and a player standing in elsewhere."""
    for objnum in (LOGIN_ROOM,):
        if not db.valid(objnum):
            db._create_object_with_objnum(objnum, parent=0, owner=0)
    login_room = db.get_object(LOGIN_ROOM)
    login_room.name = 'Login Room'
    login_room.add_property('is_room', True)

    # $globals.login_room is what object_utils.login_room() resolves.
    if not db.valid(19):
        db._create_object_with_objnum(19, parent=0, owner=0)
    holder = db.get_object(19)
    holder.name = 'Globals'
    holder.add_property('login_room', LOGIN_ROOM)
    sysobj = db.get_object(0) if db.valid(0) else db._create_object_with_objnum(0, parent=0, owner=0)
    sysobj.add_property('globals', '#19')

    elsewhere = db.create_object(parent=0, owner=0)
    elsewhere.name = 'Somewhere In Character'

    player = db.create_object(parent=0, owner=0)
    player.name = 'Tester'
    player.move_to(elsewhere.objnum, db)
    player.add_property('last_location', elsewhere.objnum)
    return login_room, elsewhere, player


def _run_login(server):
    """Build the connection and run its login inside a live event loop.

    asyncio.StreamReader() binds to the running loop at construction, so
    it cannot be created before asyncio.run() starts one.
    """
    async def scenario():
        conn = WebSocketConnection(asyncio.StreamReader(), FakeWriter(), server)
        return await conn._handle_login()
    return asyncio.run(scenario())


def _install_login_handler(monkeypatch, player, reconnect):
    """Stand in for LoginHandler, reporting a chosen reconnect outcome."""
    class StubHandler:
        def __init__(self, *_args, **_kwargs):
            self.reconnect = reconnect

        async def run(self, send=None, read_line=None):
            return player

    monkeypatch.setattr(moo.login, 'LoginHandler', StubHandler)


def test_takeover_leaves_the_character_where_it_was(db, server, monkeypatch):
    """A reconnect must not relocate the player.

    An IC character reconnecting is still standing in the world; moving
    them to the OOC login room takes them out of play.
    """
    _login, elsewhere, player = _make_world(db)
    _install_login_handler(monkeypatch, player, reconnect=True)

    assert _run_login(server) is True

    assert player._location_id == elsewhere.objnum
    assert player.has_flag(ObjectFlags.PLAYER)


def test_takeover_does_not_overwrite_last_location(db, server, monkeypatch):
    """The poisoning half of the bug.

    puppet() sends a character back to ``last_location``. Overwriting it
    with the login room on every reconnect means the portal delivers them
    to the lobby forever after -- and it is self-perpetuating, because the
    next unpuppet stores the lobby again.
    """
    _login, elsewhere, player = _make_world(db)
    _install_login_handler(monkeypatch, player, reconnect=True)

    _run_login(server)

    assert getattr(player, 'last_location') == elsewhere.objnum


def test_normal_login_still_moves_to_the_login_room(db, server, monkeypatch):
    """The takeover fix must not break an ordinary login."""
    _login, elsewhere, player = _make_world(db)
    _install_login_handler(monkeypatch, player, reconnect=False)

    assert _run_login(server) is True

    assert player._location_id == LOGIN_ROOM
    assert getattr(player, 'last_location') == LOGIN_ROOM


def test_the_splash_shows_the_world_version_when_there_is_one():
    """
    A player arriving at your game cares which game it is, not which
    server it runs on -- and a world under development moves at its own
    pace.  #0.version is where a world says so.

    Not the old arrangement returning.  That read an *engine* version
    copied into the database once and left to rot, so a 0.9 server
    introduced itself as 0.7.  A world version cannot rot that way,
    because nothing but the world is entitled to write it.
    """
    from moo.login import _world_version

    class Sysobj:
        version = '0.0.5-alpha'

    class DB:
        def __init__(self, obj): self._o = obj
        def get_object(self, n): return self._o

    assert _world_version(DB(Sysobj())) == '0.0.5-alpha'


def test_a_world_with_no_version_falls_back_to_the_engine():
    """A starter world nobody has made into a game shows the engine."""
    from moo.login import _world_version

    class Bare:
        pass

    class Raises:
        def get_object(self, n): raise KeyError(n)

    class DB:
        def __init__(self, obj): self._o = obj
        def get_object(self, n): return self._o

    assert _world_version(DB(Bare())) == ''
    assert _world_version(Raises()) == ''      # the splash must still render
