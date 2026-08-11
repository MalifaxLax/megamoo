"""
``obj.msg()`` is native, and an override still wins.

It used to be a three-statement verb on #1 that forwarded to ``notify()``,
at about 150x the cost of the primitive it called -- paid on every line of
every room description, and again per listener for every room broadcast.
At 500 players that is the hottest path in the engine.

The thing that made it a verb was worth keeping: an object can define its
own ``msg`` and filter what it hears, which is how a deafened character
works. So the native path asks ``find_verb`` first, and only an object
that genuinely overrides messaging pays for a dispatch.

Both halves need a test. The fast path is easy to keep working and easy to
make silently wrong -- and if the override half breaks, nothing raises:
a deafened character simply starts hearing everything again, which no
stack trace will ever tell you about.
"""
import types

import pytest

from moo import builtins
from moo.objects import MOOObject


class Recorder:
    """Stands in for the notify primitive."""

    def __init__(self):
        self.calls = []

    def __call__(self, target, message, **kwargs):
        self.calls.append((getattr(target, 'objnum', target), message, kwargs))


@pytest.fixture
def obj(monkeypatch):
    """A bare MOOObject with a stubbed database and notify."""
    o = MOOObject(objnum=42)
    verbs = {}

    def find_verb(name, database=None):
        return (42, verbs[name]) if name in verbs else (None, None)

    # object.__setattr__, not `o.find_verb = ...`: MOOObject.__setattr__
    # routes any non-native name to the MOO property system, so a plain
    # assignment here would quietly create a *property* called find_verb
    # and leave the real method in place -- the stub would never run and
    # every test below would pass for the wrong reason.
    object.__setattr__(o, 'find_verb', find_verb)
    o.__dict__['_database'] = object()

    recorder = Recorder()
    monkeypatch.setattr(builtins, 'notify', recorder)
    return o, verbs, recorder


def test_the_default_path_calls_notify_directly(obj):
    o, _verbs, notified = obj
    o.msg('You see nothing special.')
    assert len(notified.calls) == 1
    objnum, message, kwargs = notified.calls[0]
    assert objnum == 42
    assert message == 'You see nothing special.'
    assert kwargs['sub'] is None and kwargs['svals'] is None


def test_substitution_context_is_passed_through(obj):
    o, _verbs, notified = obj
    actor = types.SimpleNamespace(objnum=7)
    target = types.SimpleNamespace(objnum=8)
    o.msg('&S hits &d.', sub=actor, dob=target)
    _, _, kwargs = notified.calls[0]
    assert kwargs['sub'] is actor
    assert kwargs['dob'] is target


def test_raw_string_slots_reach_the_substitution_engine(obj):
    """s0/s1/... are the &0/&1 slots, and only those keys qualify."""
    o, _verbs, notified = obj
    o.msg('You pay &0 for &1.', s0='three coins', s1='a beer', sub=None)
    _, _, kwargs = notified.calls[0]
    assert kwargs['svals'] == {'s0': 'three coins', 's1': 'a beer'}


def test_a_kwarg_that_only_looks_like_a_slot_is_not_one(obj):
    o, _verbs, notified = obj
    o.msg('hello', style='shout')
    _, _, kwargs = notified.calls[0]
    assert kwargs['svals'] is None


def test_an_override_verb_wins(obj, monkeypatch):
    """
    The deafened-character case, and the only reason this is not a
    plain function call.
    """
    o, verbs, notified = obj
    verbs['msg'] = object()          # any truthy verb definition

    dispatched = []

    def fake_make_call_verb(_pobj, _db, _depth):
        def call(target, verb_name, **kwargs):
            dispatched.append((target.objnum, verb_name, kwargs.get('args')))
        return call

    monkeypatch.setattr(builtins, 'make_call_verb', fake_make_call_verb)

    from moo.verb_context import verb_ctx
    token = verb_ctx.set((o, object(), 0))
    try:
        o.msg('You hear nothing.')
    finally:
        verb_ctx.reset(token)

    assert dispatched == [(42, 'msg', 'You hear nothing.')]
    assert notified.calls == [], 'the override must not be bypassed'


def test_without_a_verb_context_an_override_still_gets_the_line_through(obj):
    """
    A ticker firing outside any verb has nothing to dispatch under.

    Falling back to notify is the deliberate choice: the player hears the
    line unfiltered, rather than silence. Losing output is the worse of
    the two failures.
    """
    o, verbs, notified = obj
    verbs['msg'] = object()

    from moo.verb_context import verb_ctx
    assert verb_ctx.get(None) is None, 'a previous test leaked a context'

    o.msg('The poison burns.')

    assert len(notified.calls) == 1
    assert notified.calls[0][1] == 'The poison burns.'


def test_a_broken_find_verb_does_not_lose_the_message(obj, monkeypatch):
    o, _verbs, notified = obj

    def boom(_name, _database=None):
        raise RuntimeError('verb table is on fire')

    object.__setattr__(o, 'find_verb', boom)
    o.msg('still delivered')
    assert len(notified.calls) == 1


@pytest.mark.parametrize('verb', ['msg', 'msg_room'])
def test_the_starter_world_ships_no_messaging_verb_on_root(verb):
    """
    Each default lives in exactly one place.

    A `msg` or `msg_room` verb on #1 would never be called -- the native
    methods shadow both, because a real Python method always beats a verb
    of the same name. Shipping one would mean a default that reads like
    the implementation and is not, which is the failure that took two
    passes to find in `msg_room` and would have taken a third.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    assert not (root / 'moo' / 'templates' / 'starter'
                / 'verbs' / '1' / f'{verb}.py').exists()
