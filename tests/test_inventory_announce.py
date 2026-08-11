"""
The GMCP inventory announce: who gets it, when, and how often.

Three things here have already been wrong once, and none of them fail
loudly -- the announce is wrapped in a bare ``except`` on purpose, because
a readout panel is not worth a player's command. That makes it exactly the
kind of code that rots without noticing, so it gets tests.

The interesting one is ``resume``. ``@delete`` asks "are you sure?" before
it recycles anything, and both command loops feed that answer straight
into the generator and ``continue`` -- nothing on that path goes through
``execute_command``, where the announce for an ordinary command lives. So
deleting the thing in your hand changed the world and told no one, and the
browser client went on showing it.
"""
import types

import pytest

from moo import builtins
from moo.utils import InteractiveSession


class FakeConn:
    """A connection that records GMCP rather than sending it."""

    def __init__(self, gmcp=True):
        self.protocols = {'gmcp'} if gmcp else set()
        self.sent = []

    def send_gmcp_sync(self, package, payload):
        self.sent.append((package, payload))


class PlainConn:
    """A connection with no GMCP at all -- a bare telnet session."""

    protocols = set()


@pytest.fixture
def player(monkeypatch):
    """
    A player whose ``inv_data`` returns whatever the test puts in `items`.

    Patched at the seams the announce actually uses: the connection
    registry, the verb-context setup, and the verb caller.
    """
    obj = types.SimpleNamespace(objnum=99)
    state = {'items': [], 'conn': FakeConn(), 'raises': None}

    monkeypatch.setattr(builtins, '_database', object(), raising=False)
    monkeypatch.setattr('moo.network.get_connection_for_player',
                        lambda num: state['conn'])
    monkeypatch.setattr('moo.verb_context.set_verb_context',
                        lambda *a, **k: None)
    monkeypatch.setattr('moo.verb_context.clear_verb_context',
                        lambda *a, **k: None)

    def fake_make_call_verb(_obj, _db):
        def call(target, verb_name, *a, **k):
            if verb_name != 'inv_data':
                raise KeyError(verb_name)
            if state['raises'] is not None:
                raise state['raises']
            return state['items']
        return call

    monkeypatch.setattr(builtins, 'make_call_verb', fake_make_call_verb)
    return obj, state


def test_it_sends_what_inv_data_returned(player):
    obj, state = player
    state['items'] = [{'num': 5, 'name': 'a sword', 'where': 'right'}]
    builtins.send_inventory_gmcp(obj)
    assert state['conn'].sent == [
        ('Char.Inventory', {'items': state['items']})]


def test_an_unchanged_inventory_is_not_resent(player):
    """This runs after every command; most commands move nothing."""
    obj, state = player
    state['items'] = [{'num': 5, 'name': 'a sword'}]
    builtins.send_inventory_gmcp(obj)
    builtins.send_inventory_gmcp(obj)
    assert len(state['conn'].sent) == 1


def test_a_change_is_sent(player):
    obj, state = player
    state['items'] = [{'num': 5, 'name': 'a sword'}]
    builtins.send_inventory_gmcp(obj)
    state['items'] = []
    builtins.send_inventory_gmcp(obj)
    assert len(state['conn'].sent) == 2
    assert state['conn'].sent[-1] == ('Char.Inventory', {'items': []})


def test_a_telnet_client_without_gmcp_is_left_alone(player):
    """
    No panel, no frames, and above all no crash.

    Most MUD clients are not browsers, and a plain telnet session has no
    way to render this. It must cost such a player nothing.
    """
    obj, state = player
    state['conn'] = PlainConn()
    state['items'] = [{'num': 5, 'name': 'a sword'}]
    builtins.send_inventory_gmcp(obj)          # must not raise
    assert not hasattr(state['conn'], 'sent')


def test_a_world_with_no_inv_data_verb_sends_nothing(player, monkeypatch):
    obj, state = player

    def no_verb(_obj, _db):
        def call(*a, **k):
            raise KeyError('inv_data')
        return call

    monkeypatch.setattr(builtins, 'make_call_verb', no_verb)
    builtins.send_inventory_gmcp(obj)
    assert state['conn'].sent == []


def test_a_failing_inv_data_does_not_reach_the_player(player):
    obj, state = player
    state['raises'] = RuntimeError('the world is on fire')
    builtins.send_inventory_gmcp(obj)          # must not raise
    assert state['conn'].sent == []


def test_resuming_an_interactive_verb_announces(player, monkeypatch):
    """
    The ``@delete`` case: the work happens after the confirmation.

    Neither command loop calls ``execute_command`` for the answer to a
    prompt, so if ``resume`` does not announce, nothing does.
    """
    obj, state = player
    calls = []
    monkeypatch.setattr(builtins, 'send_inventory_gmcp',
                        lambda p: calls.append(p))

    def confirm():
        answer = yield 'Are you sure? [y/n] '
        state['items'] = [] if answer == 'y' else state['items']

    session = InteractiveSession(confirm(), obj, db=None).start()
    assert not session.finished
    assert calls == []                      # nothing has happened yet

    session.resume('y')
    assert session.finished
    assert calls == [obj]


def test_a_broken_announce_does_not_break_the_session(player, monkeypatch):
    obj, _ = player

    def boom(_p):
        raise RuntimeError('no connection')

    monkeypatch.setattr(builtins, 'send_inventory_gmcp', boom)

    def confirm():
        yield 'ok? '

    session = InteractiveSession(confirm(), obj, db=None).start()
    session.resume('y')                     # must not raise
    assert session.finished
