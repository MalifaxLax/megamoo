"""
``read()`` -- take a line of input from inside a running verb.

MOO's ``read()`` blocks the verb until the player types something, and
the line goes to the verb rather than to the command parser.  Roughly one
ported verb in a hundred uses it, and until now every one of them was a
hole in the translation.

Why this is not the @interactive decorator
------------------------------------------

MegaMOO already redirects input, in :func:`moo.utils.interactive`: the
verb becomes a generator, ``yield`` hands control back, and the command
loop routes the next line into ``generator.send()``.  That works well and
this module does not replace it.

It cannot serve ``read()`` though, because it changes how the verb is
*written*.  A generator suspends only at a ``yield`` in its own body, so
a ``read()`` three calls deep -- which is where ported code puts it,
inside ``$command_utils:yes_or_no`` and friends -- cannot suspend the
verb that called it.  Rewriting a ported core to thread ``yield`` up
through every intermediate call is not porting.

So ``read()`` is built the way ``suspend()`` was, and for the same
reason: a parked thread keeps the whole Python stack, so the verb code
stays ordinary and the call can be at any depth.

What happens, in order
----------------------

1. The verb thread registers a :class:`PendingRead` on the connection and
   sends the prompt.
2. It **releases the baton** and waits.  This is the part that must not be
   got wrong: the baton serialises verb execution, and a verb that waited
   while holding it would stop every other player in the game until this
   one typed something.
3. The command loop, seeing a pending read, hands it the next line
   instead of parsing it as a command.
4. The verb thread wakes, takes the baton back, and ``read()`` returns.

Every way this can fail, and what it does
-----------------------------------------

An input wait is the easiest place in a server to leak a thread, so the
failures are enumerated rather than discovered:

*The player disconnects.*  Teardown fails every pending read on the
connection, so the verb raises instead of waiting for a line that is
never coming.

*The player says nothing.*  There is a timeout.  MOO has none, but MOO is
not holding a pool thread; an unbounded wait here would lose a worker per
abandoned prompt until the pool ran dry.

*Two verbs read the same connection.*  The second is refused.  Silently
queueing them would make the player's answer go to whichever verb
happened to ask first, which is not visible from either verb's code.

*An @interactive session is already running.*  Refused, for the same
reason -- two mechanisms competing for one input stream.

*The verb is not running for a connected player* -- a scheduled task, a
forked block.  Refused, because there is nobody to ask.
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger('megamoo.read')

__all__ = ['PendingRead', 'read', 'deliver_line', 'has_pending_read',
           'fail_pending_reads', 'MAX_READ_WAIT']

#: How long a verb may wait for a line before giving up.  MOO waits for
#: ever; here a parked verb holds a thread from the verb pool, so an
#: abandoned prompt has to end by itself or the pool drains one worker at
#: a time.
MAX_READ_WAIT = 300.0


class ReadAborted(Exception):
    """A pending read ended without a line.  Carries why."""


class PendingRead:
    """
    One verb waiting on one connection for one line.

    The event is set by the connection's thread and waited on by the
    verb's, which is why this is a threading.Event and not an asyncio
    one: those two live on different threads, and the loop must never
    block on the verb.

    Attributes:
        line:   The line, once it arrives.
        failed: Why the wait ended, if it ended badly.
    """

    __slots__ = ('_event', 'line', 'failed')

    def __init__(self):
        self._event = threading.Event()
        self.line: Optional[str] = None
        self.failed: Optional[str] = None

    def deliver(self, line: str) -> None:
        """Hand over a line and wake the verb."""
        self.line = line
        self._event.set()

    def fail(self, why: str) -> None:
        """End the wait without a line."""
        self.failed = why
        self._event.set()

    def wait(self, timeout: float) -> bool:
        """Block until a line arrives, or *timeout* seconds pass."""
        return self._event.wait(timeout)


def has_pending_read(conn) -> bool:
    """Whether *conn* has a verb waiting on it for a line."""
    return getattr(conn, '_pending_read', None) is not None


def deliver_line(conn, line: str) -> bool:
    """
    Give *line* to whatever verb is waiting on *conn*.

    Called from the command loop before it parses anything, so that a
    line meant for a verb is never also run as a command.

    Args:
        conn: The connection.
        line: What the player typed.

    Returns:
        bool: True if a verb took it, False if the line is an ordinary
        command.
    """
    pending = getattr(conn, '_pending_read', None)
    if pending is None:
        return False
    conn._pending_read = None
    pending.deliver(line)
    return True


def fail_pending_reads(conn, why: str = 'disconnected') -> None:
    """
    End any wait on *conn* without a line.

    Called from connection teardown.  Without it a verb parked on a
    dropped connection would sit until the timeout, holding a worker for
    a player who has gone.

    Args:
        conn: The connection.
        why: What to tell the verb.
    """
    pending = getattr(conn, '_pending_read', None)
    if pending is None:
        return
    conn._pending_read = None
    pending.fail(why)


def read(who=None, prompt: str = '') -> str:
    """
    MOO's ``read()``: wait for a line from a player, inside a verb.

    Args:
        who: Whose input to read.  Defaults to the acting player.  Reading
            somebody else's requires wizard permissions, as in MOO --
            otherwise any verb could take a line meant for the command
            parser out of another player's session.
        prompt: Optional text to send first.

    Returns:
        str: The line, without its terminator.

    Raises:
        MOOError: If there is nobody to ask, somebody is already asking
            them, the caller may not, or nothing arrives in time.
    """
    from .properties import MOOError
    from . import verb_baton
    from .network import get_connection_for_player
    from .verb_context import verb_ctx

    ctx = verb_ctx.get()
    actor = ctx[0] if ctx else None

    target = who if who is not None else actor
    if target is None:
        raise MOOError('read() outside a player command: there is nobody '
                       'to read from')

    if who is not None and actor is not None:
        same = (getattr(who, 'objnum', who) == getattr(actor, 'objnum', actor))
        if not same and not getattr(actor, 'wizard', False):
            raise MOOError('read() on another player requires wizard '
                           'permissions')

    num = getattr(target, 'objnum', target)
    conn = get_connection_for_player(int(num))
    if conn is None:
        raise MOOError(f'read(): #{num} is not connected')

    session = getattr(conn, '_interactive_session', None)
    if session is not None and not getattr(session, 'finished', True):
        raise MOOError('read(): an interactive session already has this '
                       'connection')
    if has_pending_read(conn):
        raise MOOError('read(): another verb is already reading from this '
                       'connection')

    if not verb_baton.holder():
        raise MOOError('read() outside verb execution')

    pending = PendingRead()
    conn._pending_read = pending
    if prompt:
        try:
            conn.queue_message(prompt)
        except Exception:
            try:
                target.msg(prompt)
            except Exception:
                pass

    # From here the baton is not ours, so nothing below may touch shared
    # state until it is taken back.
    verb_baton.release()
    try:
        got = pending.wait(MAX_READ_WAIT)
    finally:
        verb_baton.acquire()

    if not got:
        # The wait timed out.  Clearing the slot matters: leaving a dead
        # PendingRead behind would make the player's next line vanish
        # into a verb that stopped listening.
        if getattr(conn, '_pending_read', None) is pending:
            conn._pending_read = None
        raise MOOError('read(): nothing was typed in time')
    if pending.failed:
        raise MOOError(f'read(): {pending.failed}')
    return pending.line or ''


def read_lines(max_lines=None, terminator: str = '.') -> list:
    """
    Read lines from a player until they type a lone ``.``.

    The shape every editor in every MOO uses, and the one MegaMOO's own
    @program already implements privately.  MOO's cores spell it
    ``$command_utils:read_lines()``; ported code calls it thirteen times
    across LambdaCore, for note text, mail bodies and verb source.

    Args:
        max_lines: Stop after this many lines, or None for no limit.  MOO
            takes the same optional cap.
        terminator: The line that ends input.  A lone ``.`` by convention,
            and the reason a line of just ``.`` cannot be entered directly.

    Returns:
        list: The lines, without the terminator.  Empty if the player ended
        input immediately.

    Note:
        Blocks the calling verb, on the same machinery as :func:`read` --
        the verb is parked and the world keeps running.
    """
    lines = []
    while max_lines is None or len(lines) < int(max_lines):
        line = read()
        if line is None or line.strip() == terminator:
            break
        lines.append(line)
    return lines
