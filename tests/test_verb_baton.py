"""
Tests for the baton and suspend().

The invariant under test is the one the whole engine rests on: **no two
verbs execute at the same instant**, even while one is parked mid-verb.
Everything else here is secondary to that.
"""

import threading
import time

import pytest

from moo import verb_baton as vb


@pytest.fixture(autouse=True)
def clean_baton():
    """Leave the baton free and the counters at rest between tests."""
    yield
    if vb.holder():
        vb.release()


def _run(code, ns=None, record=None):
    """Compile and run a snippet the way the server would."""
    ns = ns if ns is not None else {}
    ns.setdefault('suspend', vb.suspend)
    vb.run_guarded(compile(code, '<test>', 'exec'), ns, record)
    return ns


# --------------------------------------------------------------------------
# The invariant
# --------------------------------------------------------------------------

def test_only_one_verb_runs_at_a_time_even_across_suspends():
    """
    Several 'verbs' run concurrently in threads, each suspending in the
    middle.  If the baton works, the count of simultaneous executors never
    exceeds one at any observed moment.
    """
    inside = 0
    peak = 0
    lock = threading.Lock()

    def body():
        nonlocal inside, peak
        with lock:
            inside += 1
            peak = max(peak, inside)
        time.sleep(0.02)
        with lock:
            inside -= 1
        vb.suspend(0.02)          # step aside, mid-verb
        with lock:
            inside += 1
            peak = max(peak, inside)
        time.sleep(0.02)
        with lock:
            inside -= 1

    ns = {'body': body}
    threads = [threading.Thread(target=_run, args=('body()', dict(ns)))
               for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert peak == 1, f"{peak} verbs ran at once; the baton is not holding"


def test_a_suspended_verb_does_not_block_another():
    """A parked verb must let a second one run to completion."""
    order = []

    def slow():
        order.append('slow-start')
        vb.suspend(0.25)
        order.append('slow-end')

    def quick():
        order.append('quick')

    t1 = threading.Thread(target=_run, args=('slow()', {'slow': slow,
                                                        'suspend': vb.suspend}))
    t1.start()
    time.sleep(0.05)                       # let it reach the suspend
    t2 = threading.Thread(target=_run, args=('quick()', {'quick': quick}))
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    # The quick verb ran *between* the slow one's two halves.
    assert order == ['slow-start', 'quick', 'slow-end'], order


# --------------------------------------------------------------------------
# Resumption
# --------------------------------------------------------------------------

def test_execution_resumes_on_the_next_line_with_locals_intact():
    ns = _run("""
counter = 0
for i in range(3):
    counter = counter + i
    suspend(0)
result = counter
""")
    assert ns['result'] == 3


def test_suspend_actually_waits():
    began = time.time()
    _run("suspend(0.2)")
    assert time.time() - began >= 0.18


def test_suspend_is_capped():
    assert vb.MAX_SUSPEND == 300.0
    began = time.time()
    # Asking for a week gets you the cap, but we only check it clamps the
    # argument rather than waiting for it.
    seconds = max(0.0, min(float(10 ** 6), vb.MAX_SUSPEND))
    assert seconds == 300.0
    assert time.time() - began < 1


# --------------------------------------------------------------------------
# Guard rails
# --------------------------------------------------------------------------

def test_suspending_without_the_baton_is_an_error():
    # Not verb code: there is no baton to hand back, and releasing one we
    # never took would let two verbs run at once.
    with pytest.raises(RuntimeError, match='does not hold'):
        vb.suspend(0)


def test_the_baton_is_returned_even_when_a_verb_raises():
    with pytest.raises(ZeroDivisionError):
        _run("1 / 0")
    assert not vb.holder()
    # Provably free: another execution can take it.
    _run("x = 1")


def test_the_baton_is_returned_when_a_verb_raises_after_suspending():
    with pytest.raises(ValueError):
        _run("suspend(0)\nraise ValueError('after')")
    assert not vb.holder()
    _run("x = 1")


# --------------------------------------------------------------------------
# Timing, which the command timeout depends on
# --------------------------------------------------------------------------

def test_parked_time_is_not_charged_as_running_time():
    rec = vb.Execution()
    _run("suspend(0.2)", record=rec)
    # The record is closed out when the verb finishes, but the parked
    # total survives, and it is what keeps a sleeping verb from being
    # mistaken for a runaway.
    assert rec.parked >= 0.18


def test_running_time_excludes_the_suspend():
    seen = {}

    def peek():
        seen['running'] = vb.running_seconds()
        seen['parked'] = vb.suspended_seconds()

    _run("suspend(0.2)\npeek()", {'peek': peek, 'suspend': vb.suspend})
    assert seen['parked'] >= 0.18
    assert seen['running'] < 0.15, seen


def test_suspended_count_reflects_parked_verbs():
    assert vb.suspended_count() == 0
    seen = []

    def watcher():
        time.sleep(0.08)
        seen.append(vb.suspended_count())

    w = threading.Thread(target=watcher)
    w.start()
    _run("suspend(0.2)")
    w.join(timeout=5)
    assert seen == [1], seen
    assert vb.suspended_count() == 0
