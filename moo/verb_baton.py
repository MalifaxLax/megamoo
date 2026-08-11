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
from contextlib import contextmanager
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
                   namespace.get('caller'), namespace.get('pobj'),
                   owner=namespace.get('_verb_owner'))
        framed = True
    except Exception:
        pass

    try:
        # The whole body is one transaction: a verb that raises leaves
        # nothing half-written.  `db` comes out of the namespace the
        # dispatcher already built, so no call site has to pass it.
        with _verb_txn(namespace.get('db')):
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


@contextmanager
def exclusive():
    """
    Hold the baton for a block that is *not* verb code, and is safe to
    re-enter from code that already holds it.

    Database writes reach SQLite from outside verb execution too -- the
    API, the login flow, connection bookkeeping -- and those share one
    connection with whatever verb is running.  A commit from any of them
    would flush a verb's half-finished transaction, so they queue behind
    verbs like everything else and the "one writer at a time" rule holds
    for the whole process rather than only for verbs.

    Re-entrant by inspection rather than by lock type: the baton is a
    plain semaphore, so a verb that already holds it must *not* try to
    take it again.  Nested use is a no-op.

    Unlike :func:`guarded` this sets up no Execution record, because
    there is no verb here to charge time to.
    """
    if holder():
        yield                       # already ours; do not re-acquire
        return
    acquire()
    try:
        yield
    finally:
        release()


@contextmanager
def _verb_txn(db):
    """
    Make the verb the unit that commits, or does not.

    Writes still reach SQLite as they happen; only the commit waits, so
    a verb that raises leaves nothing behind instead of half a trade.

    ``suspend()`` and ``read()`` close the transaction before they park
    and open a fresh one on the way back -- see :func:`checkpoint_txn`.
    That is not a compromise: parking gives the baton back, so other
    verbs run and observe this one's writes, and rolling back past that
    point would erase state the world has already acted on.  LambdaMOO
    treats a suspend as a task boundary for the same reason.

    Args:
        db: The Database, or None to run untransacted.
    """
    if db is None:
        yield
        return
    _local.txn_db = db
    db.begin_verb_txn()
    try:
        yield
    except BaseException:
        db.rollback_verb_txn()
        raise
    else:
        db.commit_verb_txn()
    finally:
        _local.txn_db = None


def checkpoint_txn():
    """
    Commit the running verb's transaction, if it has one.

    Called where a verb stops being the only thing running -- before it
    parks in ``suspend()`` or waits for input in ``read()``.
    """
    db = getattr(_local, 'txn_db', None)
    if db is not None:
        try:
            db.commit_verb_txn()
        except Exception as e:                  # never break the park
            logger.warning("Verb checkpoint failed: %s", e)


def resume_txn():
    """Re-open a verb transaction after parking.  Pairs with checkpoint_txn."""
    db = getattr(_local, 'txn_db', None)
    if db is not None:
        try:
            db.begin_verb_txn()
        except Exception as e:
            logger.warning("Verb transaction resume failed: %s", e)


@contextmanager
def guarded(record: Optional['Execution'] = None, db=None):
    """
    Hold the baton for the duration of a block, and always give it back.

    :func:`run_guarded` is the version for a compiled verb body dispatched
    straight into the pool.  This one is for callers that already have
    their own way of getting into verb code -- the ticker calls through
    ``call_verb``, which pushes its own frame -- and only need the
    one-verb-at-a-time guarantee wrapped around it.

    Sets up the same :class:`Execution` record, so ``suspend()`` and
    ``read()`` work inside the block exactly as they do in a verb reached
    from a typed command.

    Args:
        record: Optional Execution the caller can watch.
        db: Database to run the block as one transaction against, so a
            verb that raises leaves nothing half-written.  None to skip.

    Yields:
        Execution: the record for this run.
    """
    acquire()
    rec = record if record is not None else Execution()
    # As in run_guarded: the clock starts after the baton is taken, so
    # queueing behind another verb is not charged to this one.
    rec.started = time.time()
    rec.parked = 0.0
    _local.record = rec
    try:
        with _verb_txn(db):
            yield rec
    finally:
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
    # Commit before parking.  Giving the baton back lets other verbs run
    # and see what this one has written, so its transaction cannot stay
    # open across the gap -- and rolling back past this point later would
    # erase state the world has already acted on.
    checkpoint_txn()
    release()
    try:
        # A plain sleep is enough: the baton is what serialises verbs, and
        # this thread holds none of it while parked.
        time.sleep(seconds)
    finally:
        acquire()
        resume_txn()
        rec = getattr(_local, 'record', None)
        if rec is not None:
            # Charged as parked, not running, so the command timeout does
            # not accuse a sleeping verb of running away.
            rec.parked += time.time() - began
        with _count_lock:
            _suspended -= 1
