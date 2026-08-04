"""
Slow work, off the verb thread.

Verbs run one at a time -- ``server.py`` serialises them deliberately,
because verb code is not thread-safe and a great deal of it does
read-modify-write on shared objects.  The consequence is that *anything*
blocking inside a verb stops the whole world: every player, every ticker,
for the full duration.  A two-second call to a language model would freeze
the game for two seconds.

This module is the way out that does not require concurrency.  A verb hands
over a piece of slow work and returns immediately; the work happens on a
separate pool that never touches the verb thread; and when it finishes, the
answer is delivered by *calling a verb* through the normal task queue.  At
no point do two verbs run at once, so nothing about the execution model
changes.

    # in a verb -- returns at once, nothing blocks
    request('http://127.0.0.1:11434/api/generate',
            reply='npc_said', on=this,
            json={'model': 'llama3.2', 'prompt': greeting, 'stream': False})

    # in npc_said on the same object, some time later
    if ok:
        this.msg_room(body, sub=this)

The reply verb receives ``ok``, ``status``, ``body``, ``error`` and ``tag``
as ordinary variables, because ``call_verb`` keyword arguments arrive in the
callee's namespace.

The response is never compiled.  It travels as a *value* in the delivering
task's namespace, so a model that emits something resembling Python -- or a
hostile endpoint that does so deliberately -- cannot get it executed.

Only the standard library is used, keeping the engine's zero-dependency
promise.
"""

import json as _json
import logging
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger('megamoo.async_io')

__all__ = ['submit', 'http_fetch', 'set_pool_size', 'pending_count', 'shutdown']

#: Work happens here, never on the verb pool.  Several at once is fine --
#: these threads only wait on sockets; they never touch a MOOObject.
_pool: Optional[ThreadPoolExecutor] = None
_pool_size = 4
_lock = threading.Lock()
_pending = 0

#: Refuse to hold a socket open forever; a wedged endpoint should not leak
#: a thread per call.
DEFAULT_TIMEOUT = 30.0

#: Truncate enormous replies rather than dropping a megabyte into a
#: property.  Generous enough for any sane model response.
MAX_BODY = 256 * 1024


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=_pool_size,
                                       thread_name_prefix='moo-io')
        return _pool


def set_pool_size(n: int) -> None:
    """Set how many slow operations may be in flight.  Before first use."""
    global _pool_size
    with _lock:
        if _pool is not None:
            raise RuntimeError("the I/O pool is already running")
        _pool_size = max(1, int(n))


def pending_count() -> int:
    """How many operations are currently in flight."""
    return _pending


def shutdown() -> None:
    """Stop the pool.  Called on server shutdown."""
    global _pool
    with _lock:
        if _pool is not None:
            _pool.shutdown(wait=False)
            _pool = None


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def _deliver(result: Dict[str, Any], on, reply: str, tag: Any, db) -> None:
    """
    Queue a task that calls *reply* on *on* with the result.

    Runs on an I/O thread, so it must not touch game objects -- it only
    builds a task and hands it to the queue, which has its own lock.  The
    verb itself runs later, on the verb thread, one at a time as usual.
    """
    from .tasks import Task, TaskContext, get_task_queue

    queue = get_task_queue()
    if queue is None:
        logger.error("no task queue; dropping reply for %r", reply)
        return

    objnum = getattr(on, 'objnum', on)

    task = Task(TaskContext(
        player=objnum,
        this=objnum,
        caller=0,
        verb=f'<async {reply}>',
        args=[],
        argstr='',
    ))

    # The payload travels as data in the namespace.  It is never part of
    # the code string, so nothing in a response can be executed.
    task.delayed_code = (
        "call_verb(_on, _reply, ok=_ok, status=_status, "
        "body=_body, error=_error, tag=_tag)"
    )
    # The delivering namespace is built from scratch here, so it must carry
    # call_verb itself.  delay()/fork() get it free by saving the calling
    # verb's whole namespace; there is no calling verb to inherit from.
    from .builtins import make_call_verb
    task.delayed_context = {
        'call_verb': make_call_verb(on, db),
        '_on': on,
        '_reply': reply,
        '_ok': result.get('ok', False),
        '_status': result.get('status', 0),
        '_body': result.get('body', ''),
        '_error': result.get('error', ''),
        '_tag': tag,
        'player': on,
        'this': on,
        'db': db,
    }

    # suspend(0) means "run at the next pass of the queue" -- the same
    # mechanism delay() uses, so no new scheduling path is introduced.
    task.suspend(0)
    with queue.lock:
        queue.suspended_tasks[task.task_id] = task

    logger.debug("queued %s on #%s (task %s)", reply, objnum, task.task_id)


def submit(work: Callable[[], Dict[str, Any]], *, on, reply: str,
           tag: Any = None, db=None) -> None:
    """
    Run *work* off the verb thread and deliver its result to a verb.

    Args:
        work:  A callable taking nothing and returning a result dict.  It
               runs on an I/O thread and must not touch game objects.
        on:    Object whose verb receives the reply.
        reply: Verb name to call.
        tag:   Passed back untouched, for matching a reply to its request.
        db:    Database handle, put into the reply's namespace.
    """
    global _pending

    def runner():
        global _pending
        try:
            result = work()
        except Exception as err:                      # never kill the thread
            logger.exception("async work failed")
            result = {'ok': False, 'status': 0, 'body': '', 'error': str(err)}
        finally:
            _pending -= 1
        try:
            _deliver(result, on, reply, tag, db)
        except Exception:
            logger.exception("could not deliver async reply")

    _pending += 1
    _get_pool().submit(runner)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def http_fetch(url: str, *, method: str = 'GET', data: Any = None,
               headers: Optional[Dict[str, str]] = None,
               timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """
    Perform one HTTP request and describe what happened.

    Never raises: a failure is a result with ``ok`` False and ``error``
    set, because the caller is a verb that has already returned and has
    nowhere to catch an exception.

    Returns:
        dict with ``ok``, ``status``, ``body`` and ``error``.
    """
    body = None
    hdrs = dict(headers or {})

    if data is not None:
        if isinstance(data, (dict, list)):
            body = _json.dumps(data).encode('utf-8')
            hdrs.setdefault('Content-Type', 'application/json')
        elif isinstance(data, bytes):
            body = data
        else:
            body = str(data).encode('utf-8')

    req = urllib.request.Request(url, data=body, headers=hdrs,
                                 method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(MAX_BODY)
            return {
                'ok': 200 <= resp.status < 300,
                'status': resp.status,
                'body': raw.decode('utf-8', errors='replace'),
                'error': '',
            }
    except urllib.error.HTTPError as err:
        raw = b''
        try:
            raw = err.read(MAX_BODY)
        except Exception:
            pass
        return {'ok': False, 'status': err.code,
                'body': raw.decode('utf-8', errors='replace'),
                'error': f'HTTP {err.code}'}
    except Exception as err:
        # Timeouts, DNS failures, refused connections, malformed URLs.
        return {'ok': False, 'status': 0, 'body': '', 'error': str(err)}
