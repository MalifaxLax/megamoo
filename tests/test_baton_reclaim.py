"""
Tests for reclaiming the baton from a verb that never finishes.

One semaphore serialises every verb in the process, so a verb that never
returns used to end the server: the command timeout gave up on *waiting*
and told the player, but the runaway kept the baton and every command
from every player afterwards blocked in ``acquire()`` until a restart.

The fix does not take the baton away from it -- that would let a second
verb run inside the first one's half-written read-modify-write, and
commit over its open transaction.  The runaway is interrupted instead,
and gives the baton back the ordinary way, through the same ``finally``
a verb that raises ZeroDivisionError goes through.

So the assertions here come in pairs: the wedge is cleared, *and* the
one-verb-at-a-time guarantee that made it a wedge is still intact.
"""

import threading
import time

import pytest

from moo import verb_baton as vb


@pytest.fixture(autouse=True)
def clean_baton():
    """
    Leave the baton free, and refuse to leave a spinning thread behind.

    A leaked runaway would burn a core for the rest of the session and
    wedge every test after this one, which is the very failure under
    test.  Better to fail loudly here.
    """
    yield
    if vb.holder():
        vb.release()
    assert vb.holder_thread() is None, (
        f"a test left the baton held by {vb.holder_thread()}")


def _spawn(code, ns=None, record=None):
    """
    Run a snippet on a daemon thread, the way the server would.

    Daemon, and never a ThreadPoolExecutor: pool workers are not daemons
    and are joined at interpreter shutdown, so one spinning verb would
    hang pytest itself on the way out rather than failing a test.

    The outcome dict captures what came out, including the VerbAbandoned,
    so the thread's own excepthook stays quiet.

    Returns:
        (thread, outcome, namespace)
    """
    ns = ns if ns is not None else {}
    outcome = {}

    def body():
        try:
            vb.run_guarded(compile(code, '<test>', 'exec'), ns, record)
        except BaseException as e:       # VerbAbandoned is one of these
            outcome['error'] = e
        else:
            outcome['ok'] = True

    t = threading.Thread(target=body, daemon=True, name='verb-under-test')
    t.start()
    return t, outcome, ns


def _spin(record=None, ns=None):
    """Start ``while True:`` and wait until it is genuinely running."""
    running = threading.Event()
    ns = dict(ns or {})
    ns['running'] = running
    t, outcome, ns = _spawn("running.set()\nwhile True:\n    pass",
                            ns, record)
    assert running.wait(5), "the runaway never started"
    # Started is not the same as holding: wait for the baton to be its.
    deadline = time.time() + 5
    while vb.holder_thread() is not t and time.time() < deadline:
        time.sleep(0.01)
    assert vb.holder_thread() is t, "the runaway is not holding the baton"
    return t, outcome


class _FakeDB:
    """
    Just enough Database for ``_verb_txn``: one value and a snapshot.

    Real rollback is SQLite's; what this pins is that the abandoned verb
    goes down the rollback path at all, rather than leaving its writes
    half-applied or -- worse -- having them committed by whoever runs
    next.
    """

    def __init__(self, purse=100):
        self.purse = purse
        self._snapshot = None
        self.committed = False
        self.rolled_back = False

    def begin_verb_txn(self):
        self._snapshot = self.purse

    def commit_verb_txn(self):
        self._snapshot = None
        self.committed = True

    def rollback_verb_txn(self):
        if self._snapshot is not None:
            self.purse = self._snapshot
        self.rolled_back = True


# --------------------------------------------------------------------------
# The wedge
# --------------------------------------------------------------------------

def test_a_runaway_verb_is_abandoned_and_the_baton_comes_back():
    rec = vb.Execution()
    t, outcome = _spin(rec)

    assert vb.abandon(rec, 'spin') is True

    t.join(timeout=5)
    assert not t.is_alive(), "the runaway did not unwind"
    assert isinstance(outcome.get('error'), vb.VerbAbandoned), outcome
    assert vb.holder_thread() is None


def test_the_next_command_runs_after_a_runaway_is_evicted():
    """
    The regression that matters.  Before, this second verb blocked in
    acquire() forever, and so did every command any player typed next.
    """
    rec = vb.Execution()
    t, _ = _spin(rec)
    vb.abandon(rec, 'spin')
    t.join(timeout=5)

    done = []
    t2, outcome2, _ = _spawn("done.append('ran')", {'done': done})
    t2.join(timeout=5)

    assert not t2.is_alive(), "the next verb is still waiting for the baton"
    assert done == ['ran']
    assert outcome2.get('ok') is True, outcome2


def test_an_abandoned_verbs_writes_are_rolled_back():
    db = _FakeDB(purse=100)
    running = threading.Event()
    rec = vb.Execution()
    t, outcome, _ = _spawn(
        "db.purse -= 40\nrunning.set()\nwhile True:\n    pass",
        {'db': db, 'running': running}, rec)
    assert running.wait(5)
    assert db.purse == 60, "the verb never made its write"

    while vb.holder_thread() is not t:
        time.sleep(0.01)
    assert vb.abandon(rec, 'debit') is True
    t.join(timeout=5)

    assert db.rolled_back is True
    assert db.committed is False
    assert db.purse == 100, "half a trade survived the eviction"


# --------------------------------------------------------------------------
# The invariant the fix must not buy this with
# --------------------------------------------------------------------------

def test_a_second_verb_does_not_start_while_the_runaway_still_holds_it():
    """
    The baton is not stolen.  A queued verb stays queued until the
    runaway has actually unwound -- if it started earlier, two verbs
    would be executing at once and the eviction would have bought the
    wedge back with corruption.
    """
    rec = vb.Execution()
    t, _ = _spin(rec)

    entered = threading.Event()
    t2, _, _ = _spawn("entered.set()", {'entered': entered})
    assert not entered.wait(0.3), "a second verb ran alongside the runaway"

    assert vb.abandon(rec, 'spin') is True
    t.join(timeout=5)
    assert entered.wait(5), "the queued verb never got the baton"
    t2.join(timeout=5)


def test_the_semaphore_is_not_force_released():
    """
    Counted rather than inferred.  A steal plus the runaway's own
    release would leave the semaphore at 2, and two verbs could then run
    at once for the rest of the process's life -- a failure that would
    otherwise show up as data loss weeks later, not as a hang.
    """
    before = vb._baton._value
    assert before == 1, before

    rec = vb.Execution()
    t, _ = _spin(rec)
    assert vb._baton._value == 0, "the baton is meant to be held"
    vb.abandon(rec, 'spin')
    t.join(timeout=5)

    assert vb._baton._value == 1, (
        f"semaphore is at {vb._baton._value}; the baton was released twice")


# --------------------------------------------------------------------------
# Who does *not* get evicted
# --------------------------------------------------------------------------

def test_a_parked_verb_is_not_abandoned():
    """
    A verb inside ``suspend()`` holds nothing and is not the problem.
    It also keeps its Execution record, so identifying the victim by
    record alone would kill a verb that is behaving.
    """
    done = []
    rec = vb.Execution()
    t, outcome, _ = _spawn("suspend(0.4)\ndone.append('resumed')",
                           {'suspend': vb.suspend, 'done': done}, rec)
    time.sleep(0.15)                       # long enough to be parked

    assert vb.abandon(rec, 'sleepy') is False

    t.join(timeout=5)
    assert done == ['resumed'], "a well-behaved suspended verb was killed"
    assert outcome.get('ok') is True, outcome


def test_a_finished_verb_is_not_abandoned():
    rec = vb.Execution()
    t, outcome, _ = _spawn("x = 1", {}, rec)
    t.join(timeout=5)
    assert outcome.get('ok') is True

    # The deadline can be noticed after the verb got out by itself; the
    # stale record must not be able to interrupt whoever holds the baton
    # by then.
    assert vb.abandon(rec, 'finished') is False


def test_a_verb_is_only_sent_one_notice():
    rec = vb.Execution()
    t, _ = _spin(rec)
    assert vb.abandon(rec, 'spin') is True
    assert vb.abandon(rec, 'spin') is False, "a second raise was queued"
    t.join(timeout=5)
    assert vb.holder_thread() is None


# --------------------------------------------------------------------------
# The documented limit, held honestly
# --------------------------------------------------------------------------

def test_a_verb_blocked_in_a_c_call_is_evicted_when_the_call_returns():
    """
    Queued, not lost.  CPython delivers an async exception at a bytecode
    boundary, and a thread inside ``time.sleep`` is not executing
    bytecode -- so the server stays wedged for the rest of the C call and
    then recovers by itself, rather than needing a restart.
    """
    done = []
    rec = vb.Execution()
    t, outcome, _ = _spawn("sleep(0.6)\ndone.append('finished')",
                           {'sleep': time.sleep, 'done': done}, rec)
    time.sleep(0.15)
    assert vb.abandon(rec, 'sleeper') is True

    t.join(timeout=0.15)
    assert t.is_alive(), "delivery should have waited for the C call"

    t.join(timeout=5)
    assert not t.is_alive(), "the exception never landed"
    assert isinstance(outcome.get('error'), vb.VerbAbandoned), outcome
    assert done == [], "the line after the C call ran anyway"
    assert vb.holder_thread() is None


# --------------------------------------------------------------------------
# Bookkeeping the timeout path depends on
# --------------------------------------------------------------------------

def test_the_record_names_the_thread_that_holds_the_baton():
    seen = {}

    def peek():
        seen['holder'] = vb.holder_thread()
        seen['self'] = threading.current_thread()

    rec = vb.Execution()
    t, outcome, _ = _spawn("peek()", {'peek': peek}, rec)
    t.join(timeout=5)

    assert outcome.get('ok') is True, outcome
    assert seen['holder'] is seen['self'] is t
    # Cleared on the way out, so a stale record cannot name a live thread.
    assert rec.thread is None
    assert vb.holder_thread() is None


def test_abandon_tolerates_a_record_that_never_ran():
    assert vb.abandon(vb.Execution(), 'never-started') is False
    assert vb.abandon(None, 'nothing') is False
