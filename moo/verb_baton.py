"""
The baton: exactly one verb runs at a time, but a verb may step aside.

MegaMOO serialises verb execution on purpose.  Verb code is not
thread-safe, and a large part of the corpus does read-modify-write on
shared objects -- ``d = dict(obj.p or {})``, mutate, assign back -- which
silently loses updates the moment two verbs interleave.  That guarantee is
load-bearing and this module does not weaken it.

What it adds is the ability to *pause* a verb without stopping the world.

Before, the only tool was ``pause()``, which sleeps the single verb thread
and freezes every player for the duration.  Now a verb can ``suspend(5)``:
it releases the baton, parks, and lets other verbs run; when its time is up
it takes the baton back and carries on from the next line, with its local
variables and call stack exactly as it left them.

At no instant do two verbs execute.  The invariant is unchanged; what
changes is that "one at a time" no longer implies "one until it finishes".

Why threads rather than coroutines
----------------------------------

Resuming mid-verb means restoring a live Python stack.  Making verbs
coroutines would do it, but every verb would have to be authored with
``await``, which changes the language game authors write.  A parked thread
keeps the stack for free and verb code stays ordinary Python.

The cost is a thread per suspended verb, so the pool bounds how many verbs
may be suspended at once.  Exceed it and new commands wait for a worker
rather than failing, which is the right way round.

What a suspend point means
--------------------------

``suspend()`` is a yield point, and the world can change across it.  An
object read before the call may have moved, changed or been recycled by
the time the verb resumes.  This is exactly MOO's own rule, and the same
care applies: re-read what matters after suspending, rather than trusting
what was read before.
"""

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger('megamoo.baton')

__all__ = [
    'Execution', 'acquire', 'release', 'run_guarded', 'suspend',
    'running_seconds', 'suspended_seconds', 'holder', 'suspended_count',
    'MAX_SUSPEND',
]

#: The baton itself.  Whoever holds it may run verb code; nobody else may.
_baton = threading.Semaphore(1)

#: Per-thread bookkeeping, so the command timeout can charge a verb for
#: time it spent *running* and not for time it spent parked.
_local = threading.local()

#: How many verbs are parked right now.
_suspended = 0
_count_lock = threading.Lock()

#: An upper bound on a single suspend.  A verb that wants longer wants a
#: scheduled task, not a parked thread holding a worker for an hour.
MAX_SUSPEND = 300.0


def acquire() -> None:
    """Take the baton, blocking until it is free."""
    _baton.acquire()
    _local.holding = True


def release() -> None:
    """Give the baton back."""
    _local.holding = False
    _baton.release()


def holder() -> bool:
    """Whether this thread currently holds the baton."""
    return getattr(_local, 'holding', False)


def suspended_count() -> int:
    """How many verbs are parked."""
    return _suspended


def running_seconds() -> float:
    """Seconds the verb on this thread has spent executing, not parked."""
    rec = getattr(_local, 'record', None)
    return rec.running_seconds() if rec is not None else 0.0


def suspended_seconds() -> float:
    """Seconds the verb on this thread has spent parked."""
    rec = getattr(_local, 'record', None)
    return rec.parked if rec is not None else 0.0


class Execution:
    """
    Timing for one verb execution, shared with whoever is awaiting it.

    The worker thread writes it and the event loop reads it, which is why
    it is an object rather than thread-local state: the loop enforcing the
    command timeout has to see how long the verb has actually been
    *running*, and thread-locals are invisible from outside the thread.
    """

    __slots__ = ('started', 'parked')

    def __init__(self):
        self.started: Optional[float] = None
        self.parked: float = 0.0

    def running_seconds(self) -> float:
        """Seconds spent executing, not counting time parked."""
        if not self.started:
            return 0.0
        return (time.time() - self.started) - self.parked


def run_guarded(compiled, namespace, record: Optional['Execution'] = None):
    """
    Execute verb code holding the baton, and always give it back.

    This is what goes into the thread pool in place of a bare ``exec``.

    Args:
        compiled:  Code object to run.
        namespace: Globals for it.
        record:    Optional :class:`Execution` the caller can watch to see
                   how long the verb has been running.
    """
    acquire()
    rec = record if record is not None else Execution()
    # The clock starts *after* the baton is taken, so time spent queuing
    # behind another verb is not charged to this one.
    rec.started = time.time()
    rec.parked = 0.0
    _local.record = rec

    # Push the outermost call frame, so callers() and caller_perms() see a
    # complete chain.  It has to happen here rather than at the dispatch
    # site: frames are thread-local and this is the thread the verb runs
    # on.  Nested calls push their own frames from call_verb.
    framed = False
    try:
        from .builtins import push_frame, pop_frame
        push_frame(namespace.get('this'), namespace.get('verb', ''),
                   namespace.get('caller'), namespace.get('pobj'))
        framed = True
    except Exception:
        pass

    try:
        exec(compiled, namespace)
    finally:
        if framed:
            try:
                pop_frame()
            except Exception:
                pass
        _local.record = None
        rec.started = None
        release()


def suspend(seconds: float = 0.0) -> None:
    """
    Step aside for *seconds*, then carry on from the next line.

    The baton goes back while this thread is parked, so other verbs run
    meanwhile.  Execution resumes here with everything local intact.

    Remember that the world may have changed across the call -- an object
    read beforehand may have moved or been recycled.  Re-read what matters.

    Args:
        seconds: How long to step aside.  ``0`` yields to anything waiting
            and comes straight back.  Capped at :data:`MAX_SUSPEND`.

    Raises:
        RuntimeError: If called from something that is not holding the
            baton, which means it is not verb code and suspending would
            release a baton it never took.
    """
    global _suspended

    if not holder():
        raise RuntimeError(
            "suspend() outside verb execution: this thread does not hold "
            "the baton, so there is nothing to step aside from")

    seconds = max(0.0, min(float(seconds), MAX_SUSPEND))

    with _count_lock:
        _suspended += 1
    began = time.time()
    release()
    try:
        # A plain sleep is enough: the baton is what serialises verbs, and
        # this thread holds none of it while parked.
        time.sleep(seconds)
    finally:
        acquire()
        rec = getattr(_local, 'record', None)
        if rec is not None:
            # Charged as parked, not running, so the command timeout does
            # not accuse a sleeping verb of running away.
            rec.parked += time.time() - began
        with _count_lock:
            _suspended -= 1
