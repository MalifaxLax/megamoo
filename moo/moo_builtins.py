"""
LambdaMOO builtins that exist here only so ported code can call them.

These are separate from :mod:`moo.builtins` on purpose.  That module is
the engine's own vocabulary, written for verbs authored here.  This one is
a compatibility surface: every name is the shape LambdaMOO gave it, even
where that shape is odd by Python's standards, because ported code was
written against MOO's spelling and @port does not rewrite arguments.

Two consequences worth stating plainly.

``random`` here is MOO's, which returns ``1..n`` **inclusive**.  Python's
``random.randrange`` is half-open, and a shim that forwarded to it would
have made every ported die roll and random pick quietly miss its top
value.  That is the sort of bug that never crashes and never gets found.

Several of these describe things this engine does not have.  MOO charges
verbs ticks and seconds from a budget; nothing here does.  Where the
answer is genuinely unavailable, the function says so in its docstring and
returns the value that makes ported code behave *correctly* rather than
the value that makes it look busy -- see :func:`ticks_left`.
"""

import logging
import random as _random
import time as _time
from typing import Any, List, Optional

from .properties import MOOError

logger = logging.getLogger('megamoo.moo_builtins')

__all__ = [
    # Types
    'typeof', 'INT', 'NUM', 'OBJ', 'STR', 'ERR', 'LIST', 'FLOAT',
    'TYPE_INT', 'TYPE_NUM', 'TYPE_OBJ', 'TYPE_STR', 'TYPE_ERR',
    'TYPE_LIST', 'TYPE_FLOAT',
    # Expression forms Python lacks
    'moo_raise', 'moo_setprop', 'moo_setitem',
    # Values and strings
    'random', 'strcmp',
    # Players and connections
    'players', 'idle_seconds', 'connected_seconds', 'connection_name',
    'boot_player',
    # Properties and verbs
    'is_clear_property', 'clear_property', 'set_verb_info',
    # The server itself
    'server_log', 'seconds_left', 'ticks_left', 'server_version',
    # Values and membership
    'equal', 'is_member', 'set_player_flag', 'listeners',
    'set_property_info', 'property_info',
]


# ---------------------------------------------------------------------------
# MOO's type constants
#
# @port turns `typeof(x) == LIST` into an isinstance(), which is how MOO
# always writes it -- but not quite always.  A core stores type constants
# in lists, passes them to helpers and compares them later, and those uses
# leaked out as undefined names.  So the constants are real values and
# typeof() really returns them.
#
# Both spellings exist because the two common cores disagree and neither
# uses the other's: JHCore writes LIST and STR, LambdaCore writes
# TYPE_LIST and TYPE_STR.
# ---------------------------------------------------------------------------

INT = TYPE_INT = 0
OBJ = TYPE_OBJ = 1
STR = TYPE_STR = 2
ERR = TYPE_ERR = 3
LIST = TYPE_LIST = 4
FLOAT = TYPE_FLOAT = 9
NUM = TYPE_NUM = INT          # MOO's older name for the integer type


def typeof(value: Any) -> int:
    """
    MOO's ``typeof()``: which type constant describes *value*.

    Args:
        value: Anything.

    Returns:
        int: One of :data:`INT`, :data:`OBJ`, :data:`STR`, :data:`ERR`,
        :data:`LIST` or :data:`FLOAT`.

    Example::

        if typeof(x) == LIST:
            ...
    """
    if isinstance(value, bool):
        return INT                     # MOO has no bool; True is 1
    if isinstance(value, int):
        return INT
    if isinstance(value, float):
        return FLOAT
    if isinstance(value, str):
        return STR
    if isinstance(value, (list, tuple)):
        return LIST
    if isinstance(value, MOOError):
        return ERR
    if hasattr(value, 'objnum'):
        return OBJ
    return OBJ if value is None else STR


# ---------------------------------------------------------------------------
# Expressions Python does not have
# ---------------------------------------------------------------------------

def moo_raise(error: Any, message: str = '', value: Any = None):
    """
    Raise *error*, from anywhere an expression is allowed.

    Python raises only as a statement, but MOO's ``raise()`` is an
    expression and the common idiom -- ``caller_perms().wizard ||
    raise(E_PERM)`` -- puts it inside one.  A function call is an
    expression, so routing through this preserves the idiom exactly
    instead of asking for the verb to be restructured by hand.

    Args:
        error: The MOO error to raise.
        message: Optional message.
        value: Optional accompanying value, kept for signature
            compatibility with MOO's three-argument form.

    Raises:
        MOOError: Always.
    """
    if isinstance(error, MOOError):
        raise error
    raise MOOError(str(message or error))


def moo_setprop(obj: Any, name: str, value: Any):
    """
    Set a property and return what was set, for use inside an expression.

    MOO allows assignment in expression position -- ``if (obj.x = f())``
    -- and Python's walrus binds plain names only.  Rather than making a
    human lift the line out, @port routes property targets through here.

    Args:
        obj: Object to write to.
        name: Property name.
        value: Value to store.

    Returns:
        *value*, so the surrounding expression sees what MOO's would.
    """
    setattr(obj, name, value)
    return value


def moo_setitem(seq: Any, index: Any, value: Any):
    """
    Set an element and return the **container**, matching MOO exactly.

    Two things here are easy to get backwards.

    *What it returns.*  ``x[1] = v`` evaluates to the whole list in MOO,
    not to ``v``, because MOO lists are values and the assignment produces
    the new list.  Returning ``value`` -- the obvious guess, and what
    :func:`moo_setprop` correctly does -- would silently change the result
    of every expression using the form.

    *How it counts.*  **The index is Python's, not MOO's.**  That looks
    wrong for a MOO compatibility shim, and it is deliberate: @port shifts
    every subscript as it translates, so by the time a target reaches this
    function ``x[1]`` has already become ``x[0]``.  Shifting again here
    would make it ``x[-1]`` -- not an error, just a write to the far end
    of the list, which is the precise failure the translator exists to
    avoid.

    Args:
        seq: List or dict to write to.
        index: An already-translated index, or a dict key.
        value: Value to store.

    Returns:
        *seq*, after the write.
    """
    seq[index] = value
    return seq


# ---------------------------------------------------------------------------
# Values and strings
# ---------------------------------------------------------------------------

def random(n: int = 2147483647) -> int:
    """
    MOO's ``random()``: a number from ``1`` to *n*, **inclusive**.

    Both ends matter.  MOO counts from one and includes the top, so
    ``random(6)`` is a die roll.  Forwarding to Python's half-open
    ``randrange`` would have dropped the top face of every die and the
    last element of every random pick, without ever raising.

    Args:
        n: The largest value that may come back.

    Returns:
        int: ``1 <= result <= n``.
    """
    n = int(n)
    if n < 1:
        return 1
    return _random.randint(1, n)


def strcmp(a: str, b: str) -> int:
    """
    MOO's ``strcmp()``: C's, so **case matters** and the result is a sign.

    MOO's other string operations fold case; this one does not, which is
    exactly why cores reach for it.

    Args:
        a: First string.
        b: Second string.

    Returns:
        int: Negative if *a* sorts first, ``0`` if equal, positive if *b*
        sorts first.
    """
    a, b = str(a), str(b)
    return (a > b) - (a < b)


# ---------------------------------------------------------------------------
# Players and connections
# ---------------------------------------------------------------------------

def _connection(who) -> Optional[Any]:
    """The live connection for *who*, or None if they are not connected."""
    try:
        from .network import get_connection_for_player
        num = getattr(who, 'objnum', who)
        return get_connection_for_player(int(num))
    except Exception:
        return None


def players() -> List[Any]:
    """
    MOO's ``players()``: every player object, connected or not.

    Not to be confused with ``connected_players()``, which is only those
    online now.  Cores use this one to iterate the whole roster.

    Returns:
        list: Player objects.
    """
    try:
        from .builtins import _database
        if not _database:
            return []
        return [o for o in _database.objects()
                if getattr(o, 'is_player', False)]
    except Exception:
        return []


def idle_seconds(who) -> int:
    """
    MOO's ``idle_seconds()``: seconds since *who* last sent a line.

    A player who has connected but not yet typed reads as idle since they
    connected, which is what MOO reports too.

    Args:
        who: A player object or object number.

    Returns:
        int: Seconds idle, or ``0`` if they are not connected.
    """
    conn = _connection(who)
    if conn is None:
        return 0
    last = getattr(conn, 'last_activity', None)
    if last is None:
        return 0
    return max(0, int((_time.time() - last.timestamp())))


def connected_seconds(who) -> int:
    """
    MOO's ``connected_seconds()``: how long *who* has been online.

    Args:
        who: A player object or object number.

    Returns:
        int: Seconds connected, or ``0`` if they are not connected.
    """
    conn = _connection(who)
    if conn is None:
        return 0
    started = getattr(conn, 'connected_at', None)
    if started is None:
        return 0
    return max(0, int((_time.time() - started.timestamp())))


def connection_name(who) -> str:
    """
    MOO's ``connection_name()``: where *who* is connected from.

    MOO's exact wording is ``"port N from HOST, port M"``.  This keeps
    the host-and-port substance in a readable form; ported code that
    prints it is fine, and ported code that *parses* it was already
    parsing a server-specific string.

    Args:
        who: A player object or object number.

    Returns:
        str: A description of the connection, or ``''`` if not connected.
    """
    conn = _connection(who)
    if conn is None:
        return ''
    return f"{getattr(conn, 'host', 'unknown')}, port {getattr(conn, 'port', 0)}"


def boot_player(who) -> None:
    """
    MOO's ``boot_player()``: disconnect *who*.

    Args:
        who: A player object or object number.
    """
    conn = _connection(who)
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        try:
            conn._disconnected = True
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Properties and verbs
# ---------------------------------------------------------------------------

def is_clear_property(obj, name: str) -> bool:
    """
    MOO's ``is_clear_property()``: does *obj* inherit this rather than
    define it.

    A "clear" property is one the object does not set itself, so it reads
    through to its parent and follows any change made there.  That maps
    exactly onto this engine: an object's own ``properties`` dict holds
    what it defines, and anything else it can read comes from an ancestor.

    Args:
        obj: The object.
        name: Property name.

    Returns:
        bool: True if *obj* inherits the value rather than holding it.
    """
    try:
        own = getattr(obj, 'properties', None) or {}
        if name in own:
            return False
        return hasattr(obj, name)
    except Exception:
        return False


def clear_property(obj, name: str) -> None:
    """
    MOO's ``clear_property()``: stop defining *name* here, inherit it.

    Args:
        obj: The object.
        name: Property name.
    """
    try:
        own = getattr(obj, 'properties', None)
        if own is not None and name in own:
            del own[name]
    except Exception:
        pass


def set_verb_info(obj, verb, info) -> None:
    """
    MOO's ``set_verb_info()``: write back what ``verb_info()`` returns.

    Args:
        obj: Object holding the verb.
        verb: Verb name, or a 1-based index into the object's verbs.
        info: ``[owner, perms, names]`` -- the same shape ``verb_info()``
            gives back.
    """
    from .builtins import _find_verbdef
    v = _find_verbdef(obj, verb)
    if v is None or not isinstance(info, (list, tuple)) or len(info) < 3:
        return
    owner, perms, names = info[0], info[1], info[2]
    v.owner = int(getattr(owner, 'objnum', owner))
    v.perms = str(perms)
    v.names = str(names).split()


# ---------------------------------------------------------------------------
# The server itself
# ---------------------------------------------------------------------------

def server_log(message: str, is_error: bool = False) -> None:
    """
    MOO's ``server_log()``: write a line to the server's log.

    Args:
        message: What to record.
        is_error: Log at error level rather than info.
    """
    (logger.error if is_error else logger.info)('%s', message)


def seconds_left() -> int:
    """
    MOO's ``seconds_left()``: how long this verb may still run.

    This one is real.  The engine already enforces a command timeout and
    already tracks how long the running verb has been executing rather
    than parked, so the remaining budget is a subtraction.

    Returns:
        int: Seconds remaining before the command timeout fires.
    """
    try:
        from .globals import COMMAND_TIMEOUT
        from .verb_baton import running_seconds
        return max(0, int(COMMAND_TIMEOUT - running_seconds()))
    except Exception:
        return 5


def ticks_left() -> int:
    """
    MOO's ``ticks_left()``: how much of the tick budget is left.

    There is no tick budget here -- this engine limits verbs by wall
    clock, not by counting operations -- so there is no honest number to
    return.  What it returns is chosen for how ported code *behaves*: the
    universal idiom is

        if (ticks_left() < 1000) suspend(0); endif

    and a large value makes that test false, so the loop runs straight
    through instead of yielding on every pass.  That is correct here,
    because the thing the idiom protects against does not exist.  A small
    or zero value would have been the more "honest-looking" choice and
    would have made every long loop in a ported core suspend constantly.

    Returns:
        int: A large constant.
    """
    return 2000000


# ---------------------------------------------------------------------------
# The rest of the tail
#
# Small, each used in a handful of verbs, and each one otherwise an
# undefined name that stopped an entire verb from being clean.
# ---------------------------------------------------------------------------

def equal(a: Any, b: Any) -> bool:
    """
    MOO's ``equal()``: deep equality, and **case-sensitive**.

    This is the whole reason it exists.  MOO's ``==`` folds case on
    strings, so ``"Foo" == "foo"`` is true; ``equal()`` is what a core
    reaches for when it must not be.

    Args:
        a: First value.
        b: Second value.

    Returns:
        bool: Whether they are equal, comparing strings exactly.
    """
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return (set(a) == set(b) and
                all(equal(a[k], b[k]) for k in a))
    return a == b


def is_member(value: Any, lst: List) -> int:
    """
    MOO's ``is_member()``: **where** *value* is, not whether it is there.

    It returns a 1-based position and ``0`` when absent, which is truthy
    exactly when membership holds -- so ported code reading it as a
    boolean is still right, and ported code using the position gets the
    position.  Comparison is case-sensitive, like :func:`equal`.

    Args:
        value: What to look for.
        lst: Where to look.

    Returns:
        int: 1-based index, or ``0`` if not present.
    """
    for i, item in enumerate(lst or [], 1):
        if equal(item, value):
            return i
    return 0


def set_player_flag(obj, value) -> None:
    """
    MOO's ``set_player_flag()``: mark an object as a player, or not.

    Args:
        obj: The object.
        value: Truthy to make it a player.
    """
    try:
        obj.is_player = bool(value)
    except Exception:
        pass


def listeners() -> List:
    """
    MOO's ``listeners()``: the objects currently receiving output.

    MOO returns ``{{object, host, port}, ...}`` for open listening
    points.  The nearest true thing here is the set of connected
    players, since that is what output actually reaches.

    Returns:
        list: ``[object, host, port]`` triples, one per connection.
    """
    out = []
    try:
        from .network import _player_connections
        for num, conn in list(_player_connections.items()):
            out.append([num, getattr(conn, 'host', 'unknown'),
                        getattr(conn, 'port', 0)])
    except Exception:
        pass
    return out


def server_version() -> str:
    """
    MOO's ``server_version()``: what server this is.

    Returns:
        str: This engine's version, not a LambdaMOO one.  Ported code
        that *displays* it is fine; ported code that compares against a
        LambdaMOO version number was already making a claim that cannot
        be honoured here, and a fake number would hide that.
    """
    try:
        from .globals import SERVER_VERSION
        return str(SERVER_VERSION)
    except Exception:
        return 'MegaMOO'


def property_info(obj, name: str):
    """
    MOO's ``property_info()``: ``{owner, perms}`` for a property.

    Args:
        obj: The object.
        name: Property name.

    Returns:
        list: ``[owner, perms]``, or ``E_PROPNF`` if there is no such
        property.
    """
    from .builtins import property_info as _pi
    return _pi(obj, name)


def set_property_info(obj, name: str, info) -> None:
    """
    MOO's ``set_property_info()``: write back what ``property_info()``
    returns.

    Args:
        obj: The object.
        name: Property name.
        info: ``[owner, perms]``.
    """
    if not isinstance(info, (list, tuple)) or len(info) < 2:
        return
    try:
        props = getattr(obj, 'properties', None) or {}
        prop = props.get(name)
        if prop is None:
            return
        prop.owner = int(getattr(info[0], 'objnum', info[0]))
        prop.perms = str(info[1])
    except Exception:
        pass
