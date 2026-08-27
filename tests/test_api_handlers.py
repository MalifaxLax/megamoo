"""Unit tests for the new JSON API command handlers (stubbed database)."""
import asyncio
from types import SimpleNamespace

from moo.api import ApiConnection, ApiServer
from moo.objects import MOOObject


class StubConfig:
    auth_token = ''
    testbot_objnum = 0
    host = '127.0.0.1'
    port = 0
    auto_port = True
    port_scan_limit = 50
    info_path = '-'          # these tests never bind; advertise nothing


def make_conn(database=None, server=None):
    api = ApiServer(database, StubConfig(), server=server)
    conn = ApiConnection(api, reader=None, writer=None)
    conn.authenticated = True
    return conn


def test_dispatch_awaits_async_handlers():
    conn = make_conn()

    async def fake_handler(args):
        return {'ok_from': 'async'}

    conn._cmd_fake = fake_handler
    result = asyncio.run(conn.dispatch({'cmd': 'fake', 'args': {}}))
    assert result == {'ok_from': 'async'}


def test_dispatch_still_supports_sync_handlers():
    conn = make_conn()
    conn._cmd_fake = lambda args: {'ok_from': 'sync'}
    result = asyncio.run(conn.dispatch({'cmd': 'fake', 'args': {}}))
    assert result == {'ok_from': 'sync'}


class StubObject:
    def __init__(self, objnum, name, location=None, contents=()):
        self.objnum = objnum
        self.name = name
        self._location_id = location
        self._content_ids = list(contents)
        self.properties = {}

    @property
    def props(self):
        return {k: p.value for k, p in self.properties.items()}

    def set_property(self, name, value):
        if name not in self.properties:
            raise KeyError(name)
        self.properties[name].value = value

    def add_property(self, name, value):
        self.properties[name] = SimpleNamespace(value=value)


class StubDatabase:
    def __init__(self, objects):
        self.objects = {o.objnum: o for o in objects}
        self.saved = []

    def get_object(self, objnum):
        return self.objects[objnum]

    def valid(self, objnum):
        return objnum in self.objects

    def save_object(self, obj):
        self.saved.append(obj.objnum)


def test_set_property_adds_when_missing():
    # player_objnum is named: the command acts as somebody now, because a
    # write with no verb context is a write the engine cannot check, and
    # that was how the API reached `auth` on any object.  Unnamed, it looks
    # for the lowest wizard, which this stub has no way to answer.
    db = StubDatabase([StubObject(10, 'Thing'), StubObject(1, 'Wiz')])
    conn = make_conn(database=db)
    result = conn._cmd_set_property(
        {'objnum': 10, 'name': 'hits', 'value': 42, 'player_objnum': 1})
    assert db.objects[10].props['hits'] == 42
    assert 10 in db.saved
    assert result['value'] == 42


def test_get_location_returns_room_name():
    room = StubObject(14, 'Town Square')
    bot = StubObject(900, 'TestBot', location=14)
    conn = make_conn(database=StubDatabase([room, bot]))
    result = conn._cmd_get_location({'objnum': 900})
    assert result == {'objnum': 900, 'location': 14,
                      'location_name': 'Town Square'}


def test_list_contents_returns_objnum_name_pairs():
    room = StubObject(14, 'Town Square', contents=(900, 901))
    conn = make_conn(database=StubDatabase(
        [room, StubObject(900, 'TestBot'), StubObject(901, 'a rat')]))
    result = conn._cmd_list_contents({'objnum': 14})
    assert result['contents'] == [
        {'objnum': 900, 'name': 'TestBot'},
        {'objnum': 901, 'name': 'a rat'},
    ]


def test_set_property_updates_existing_on_real_moo_object():
    """Handler's set/add fallback works against real MOOObject semantics."""
    obj = MOOObject(objnum=42, parent=0, owner=42)
    obj.add_property('score', 0)
    # Acts as #42 itself, which owns the property -- the ownership rule the
    # engine applies once there is a verb context to apply it in.
    db = StubDatabase([obj])
    conn = make_conn(database=db)
    result = conn._cmd_set_property(
        {'objnum': 42, 'name': 'score', 'value': 99, 'player_objnum': 42})
    assert obj.get_property('score') == 99
    assert result['value'] == 99
    assert 42 in db.saved


def test_server_status_requires_server_ref():
    conn = make_conn(server=None)
    try:
        conn._cmd_server_status({})
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
