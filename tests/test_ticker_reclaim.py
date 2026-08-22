"""
Tests for reclaiming the baton from a ticker verb that never finishes.

The same wedge as ``test_baton_reclaim.py``, reached the other way.  It
matters more here than the name suggests: a world's combat, spawning and
bleed-out live on tickers, and a ticker fires with nobody typing
anything.  So a runaway ticker stopped the world with no command to
blame it on, and the log said only that a ticker had timed out -- which
until now meant "we stopped waiting", not "we got the baton back".

Tickers are awaited through the server's own ``_await_verb`` now, the
same deadline a typed command gets, so eviction is the one mechanism
rather than two.  What is pinned here is the wiring: that a runaway
ticker really is abandoned, that the world runs again afterwards, and
that none of it was bought by force-releasing the semaphore.
"""

import asyncio
import concurrent.futures
import logging
import threading
import time

import pytest

from moo import builtins as builtins_mod
from moo import server as server_mod
from moo import verb_baton as vb
from moo.server import MegaMOOServer
from moo.ticker import TickerHandler


@pytest.fixture(autouse=True)
def clean_baton():
    """Refuse to leave the baton held, or a spinning thread behind."""
    yield
    if vb.holder():
        vb.release()
    assert vb.holder_thread() is None, (
        f"a test left the baton held by {vb.holder_thread()}")


@pytest.fixture
def short_deadline(monkeypatch):
    """
    Shorten the deadline, not the mechanism.

    ``_await_verb`` notices at its 1s poll, so a test that trips the
    deadline costs about a second whatever this is set to.
    """
    monkeypatch.setattr(server_mod, 'COMMAND_TIMEOUT', 0.1)
    return 0.1


class _DaemonExecutor(concurrent.futures.Executor):
    """
    An Executor whose threads are daemons.

    ``ThreadPoolExecutor`` is unusable here: its workers are not daemons
    and are joined at interpreter shutdown, so a single verb that failed
    to be evicted would hang pytest itself on the way out instead of
    failing a test.  ``run_in_executor`` only needs ``submit``.
    """

    def submit(self, fn, *args, **kwargs):
        fut = concurrent.futures.Future()

        def run():
            if not fut.set_running_or_notify_cancel():
                return
            try:
                fut.set_result(fn(*args, **kwargs))
            except BaseException as e:      # VerbAbandoned is one of these
                fut.set_exception(e)

        threading.Thread(target=run, daemon=True,
                         name='ticker-under-test').start()
        return fut


class _FakeDB:
    """Enough Database for ``_fire``: object lookup and a verb txn."""

    def __init__(self, obj=None, hp=100):
        self.obj = obj if obj is not None else object()
        self.hp = hp
        self._snapshot = None
        self.committed = False
        self.rolled_back = False

    def get_object(self, objnum):
        return self.obj

    def begin_verb_txn(self):
        self._snapshot = self.hp

    def commit_verb_txn(self):
        self._snapshot = None
        self.committed = True

    def rollback_verb_txn(self):
        if self._snapshot is not None:
            self.hp = self._snapshot
        self.rolled_back = True


class _FakeServer:
    """The two attributes ``_fire_due`` reaches for on the server."""

    # The real awaiter, not a stand-in: reusing it is the point of the
    # change under test.  It touches nothing on self.
    _await_verb = MegaMOOServer._await_verb

    def __init__(self, pool):
        self._verb_thread_pool = pool


def _handler(db, bodies, monkeypatch):
    """A TickerHandler wired to fake verb bodies keyed by verb name."""
    def make_call_verb(obj, _db, _depth=0):
        def call_verb(target, verb_name, *args, **kwargs):
            return bodies[verb_name](_db)
        return call_verb

    monkeypatch.setattr(builtins_mod, 'make_call_verb', make_call_verb)

    handler = TickerHandler(db)
    handler._db = db
    handler._server = _FakeServer(_DaemonExecutor())
    return handler


def _sub(verb, interval=1.0):
    return {'verb': verb, 'interval': interval,
            'next_fire': 0.0, '_in_flight': True}


def _spin(db):
    """A ticker verb that never returns -- `_td_bleed` with a bad guard."""
    while True:
        pass


# --------------------------------------------------------------------------
# The wedge, reached through a ticker
# --------------------------------------------------------------------------

def test_a_runaway_ticker_is_abandoned_and_the_baton_comes_back(
        short_deadline, monkeypatch, caplog):
    db = _FakeDB()
    handler = _handler(db, {'_td_bleed': _spin}, monkeypatch)
    sub = _sub('_td_bleed')

    with caplog.at_level(logging.ERROR):
        asyncio.run(handler._fire_due([((5, 'bleed'), sub)]))

    assert vb.holder_thread() is None, "the runaway ticker kept the baton"
    assert vb._baton._value == 1

    # Visible, and it names the verb: a ticker fires with no player
    # command to point at, so the log is the only way to find out which
    # one ran away.
    assert any('_td_bleed' in r.message and 'Abandoning runaway verb' in r.message
               for r in caplog.records), [r.message for r in caplog.records]

    # The subscription is released either way, as it was before.
    assert sub['_in_flight'] is False
    assert sub['next_fire'] > 0.0


def test_the_next_ticker_in_the_batch_still_fires(
        short_deadline, monkeypatch):
    """
    Tickers are drained in one serial queue, so the runaway used to take
    every ticker behind it as well -- combat for every character in the
    world, not just the one whose verb was broken.
    """
    ran = []
    db = _FakeDB()
    handler = _handler(db, {
        '_td_bleed': _spin,
        'critter_loop': lambda _db: ran.append('critter_loop'),
    }, monkeypatch)

    asyncio.run(handler._fire_due([
        ((5, 'bleed'), _sub('_td_bleed')),
        ((6, 'critters'), _sub('critter_loop')),
    ]))

    assert ran == ['critter_loop'], "the ticker behind the runaway never fired"
    assert vb.holder_thread() is None


def test_a_player_command_runs_after_a_runaway_ticker(
        short_deadline, monkeypatch):
    """The regression that matters: the world executes verbs again."""
    db = _FakeDB()
    handler = _handler(db, {'_td_bleed': _spin}, monkeypatch)
    asyncio.run(handler._fire_due([((5, 'bleed'), _sub('_td_bleed'))]))

    done = []
    t = threading.Thread(
        target=vb.run_guarded,
        args=(compile("done.append('ran')", '<test>', 'exec'), {'done': done}),
        daemon=True)
    t.start()
    t.join(timeout=5)

    assert not t.is_alive(), "a command is still waiting for the baton"
    assert done == ['ran']


def test_a_runaway_tickers_writes_are_rolled_back(
        short_deadline, monkeypatch):
    db = _FakeDB(hp=100)

    def bleed(_db):
        _db.hp -= 40
        while True:
            pass

    handler = _handler(db, {'_td_bleed': bleed}, monkeypatch)
    asyncio.run(handler._fire_due([((5, 'bleed'), _sub('_td_bleed'))]))

    assert db.rolled_back is True
    assert db.committed is False
    assert db.hp == 100, "half a tick of damage survived the eviction"


def test_the_semaphore_is_not_force_released(short_deadline, monkeypatch):
    """
    Counted, not inferred.  A steal plus the runaway's own release would
    leave the semaphore at 2 and let two verbs run at once from then on
    -- which in a combat tick means lost hit points, not a hang.
    """
    assert vb._baton._value == 1

    db = _FakeDB()
    handler = _handler(db, {'_td_bleed': _spin}, monkeypatch)
    asyncio.run(handler._fire_due([((5, 'bleed'), _sub('_td_bleed'))]))

    assert vb._baton._value == 1, (
        f"semaphore is at {vb._baton._value}; the baton was released twice")


# --------------------------------------------------------------------------
# Who does *not* get evicted
# --------------------------------------------------------------------------

def test_a_well_behaved_ticker_is_not_touched(short_deadline, monkeypatch):
    ran = []
    db = _FakeDB()
    handler = _handler(db, {'regen': lambda _db: ran.append('regen')},
                       monkeypatch)
    sub = _sub('regen')

    asyncio.run(handler._fire_due([((5, 'regen'), sub)]))

    assert ran == ['regen']
    assert db.committed is True and db.rolled_back is False
    assert sub['_in_flight'] is False


def test_a_ticker_is_not_charged_for_waiting_for_the_baton(
        short_deadline, monkeypatch):
    """
    The other half of using ``_await_verb``.  A fixed wallclock deadline
    counted the seconds a ticker spent queued behind somebody else's
    command, so on a busy world tickers timed out having never run.  The
    clock starts when the baton is taken.

    Here the baton is held for well past the deadline before the ticker
    can start, and the ticker must still fire.
    """
    ran = []
    db = _FakeDB()
    handler = _handler(db, {'critter_loop': lambda _db: ran.append('ran')},
                       monkeypatch)

    def squatter():
        vb.acquire()
        try:
            time.sleep(1.5)             # far longer than the deadline
        finally:
            vb.release()

    holder = threading.Thread(target=squatter, daemon=True)
    holder.start()
    while vb.holder_thread() is not holder:
        time.sleep(0.01)

    asyncio.run(handler._fire_due([((6, 'critters'), _sub('critter_loop'))]))
    holder.join(timeout=5)

    assert ran == ['ran'], "a queued ticker was timed out for waiting"
    assert vb.holder_thread() is None
