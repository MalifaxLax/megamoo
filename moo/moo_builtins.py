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
    'moo_raise', 'moo_setprop', 'moo_setitem', 'moo_listset',
    # Operators whose meaning differs from Python's
    'moo_eq', 'moo_ne', 'moo_lt', 'moo_le', 'moo_gt', 'moo_ge',
    'moo_div', 'moo_mod',
    # Values and strings
    'random', 'strcmp', 'sqrt',
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
    # System references
    'sysobj', 'has_sysobj', 'set_sysobj',
    # Tasks, verbs and dynamic dispatch
    'queued_tasks', 'call_function', 'set_verb_args', 'crypt',
    'task_stack', 'function_info',
    # Maths
    'sin', 'cos', 'tan', 'asin', 'acos', 'atan',
    'sinh', 'cosh', 'tanh', 'exp', 'log', 'log10', 'ceil', 'trunc',
    'floatstr',
    # Server measurement and connection control
    'value_bytes', 'memory_usage', 'dump_database',
    'flush_input', 'force_input', 'output_delimiters',
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


def queued_tasks() -> List:
    """
    MOO's ``queued_tasks()``: the tasks this player has waiting.

    MOO returns ``{{task-id, start-time, ticks, clock-id, programmer,
    verb-loc, verb-name, line, this}, ...}``.  The engine already tracks
    the same queue for ``@ps``, so this reshapes what it has into MOO's
    order rather than inventing a second accounting.

    ``ticks`` is 0 for the reason given in :func:`ticks_left` -- nothing
    here counts them -- and ``line`` is 0 because these verbs are Python
    source rather than a bytecode program with a counter.

    Returns:
        list: One list per queued task, in MOO's field order.
    """
    try:
        from .builtins import task_list
        rows = task_list()
    except Exception:
        return []
    out = []
    for t in rows:
        out.append([
            t.get('id', 0), t.get('start', 0), 0, 0,
            t.get('owner', t.get('player', 0)),
            t.get('this', 0), t.get('verb', ''), 0, t.get('this', 0),
        ])
    return out


def call_function(name: str, *args):
    """
    MOO's ``call_function()``: call a builtin chosen at runtime.

    Only builtins are reachable, which is MOO's rule too -- it is not a
    way to reach arbitrary Python.  The lookup goes through the same
    namespace template a verb gets, so what is callable here is exactly
    what is callable by name in a verb.

    Args:
        name: The builtin's name.
        *args: Its arguments.

    Returns:
        Whatever the builtin returns.

    Raises:
        MOOError: If there is no such builtin.
    """
    ns = {}
    try:
        from .builtins import _get_builtin_ns_template
        ns.update(_get_builtin_ns_template())
    except Exception:
        pass
    ns.update({n: globals()[n] for n in __all__ if n in globals()})
    fn = ns.get(str(name))
    if not callable(fn):
        raise MOOError(f'call_function: no builtin named {name!r}')
    return fn(*args)


def set_verb_args(obj, verb, args) -> None:
    """
    MOO's ``set_verb_args()``: set a verb's argument specification.

    This engine parses verbs by their verb *type* rather than by a stored
    ``dobj/prep/iobj`` triple, so there is nothing here for the
    specification to change -- which is why ``verb_args()`` reports the
    permissive default rather than reading one back.

    It accepts and does nothing rather than raising, because ported code
    sets this while creating a verb and would otherwise fail at a line
    that has no bearing on what the verb does.  Nothing is silently
    granted: the verb's parsing is unchanged either way.

    Args:
        obj: Object holding the verb.
        verb: Verb name or 1-based index.
        args: ``[dobj, prep, iobj]``, ignored.
    """
    return None


def crypt(text: str, salt: str = '') -> str:
    """
    MOO's ``crypt()``: the one-way hash used for stored passwords.

    MOO wraps the C library's ``crypt(3)``.  Python dropped its ``crypt``
    module in 3.13, so this uses hashlib and marks the result with a
    ``$6$``-style prefix to say what it is.

    **Hashes made here do not match hashes made by LambdaMOO.**  That
    matters in exactly one place: an imported core's existing password
    hashes cannot be verified against, so those players need new
    passwords.  Saying so is the point -- an implementation that returned
    a plausible-looking string would leave every imported account
    unopenable with no indication why.

    Args:
        text: The string to hash.
        salt: Salt.  A random one is generated if omitted.

    Returns:
        str: The salted hash, prefixed with the salt as MOO's is.
    """
    import hashlib
    import os
    if not salt:
        salt = os.urandom(6).hex()
    salt = str(salt)
    if salt.startswith('$6$'):
        salt = salt[3:].split('$')[0]
    digest = hashlib.sha512((salt + str(text)).encode()).hexdigest()
    return f'$6${salt}${digest}'


def sqrt(x) -> float:
    """
    MOO's ``sqrt()``.

    Args:
        x: A number.

    Returns:
        float: Its square root.
    """
    import math
    return math.sqrt(float(x))


# ---------------------------------------------------------------------------
# Maths
#
# MOO's floating-point builtins are C's, and so are Python's, so these are
# thin by design.  They are here rather than left to `import math` because
# a verb namespace has no modules in it -- an unwrapped math call is an
# undefined name, which is what these were before.
# ---------------------------------------------------------------------------

def _m(fn, *a):
    import math
    return getattr(math, fn)(*[float(x) for x in a])


def sin(x):
    """MOO's ``sin()``: sine of *x* radians."""
    return _m('sin', x)


def cos(x):
    """MOO's ``cos()``: cosine of *x* radians."""
    return _m('cos', x)


def tan(x):
    """MOO's ``tan()``: tangent of *x* radians."""
    return _m('tan', x)


def asin(x):
    """MOO's ``asin()``: arc sine, in radians."""
    return _m('asin', x)


def acos(x):
    """MOO's ``acos()``: arc cosine, in radians."""
    return _m('acos', x)


def atan(y, x=None):
    """
    MOO's ``atan()``: arc tangent, in radians.

    Args:
        y: The value, or the numerator of the two-argument form.
        x: If given, the denominator -- ``atan(y, x)`` is C's ``atan2``,
            which keeps the quadrant that ``atan(y / x)`` loses.

    Returns:
        float: The angle in radians.
    """
    return _m('atan', y) if x is None else _m('atan2', y, x)


def sinh(x):
    """MOO's ``sinh()``: hyperbolic sine."""
    return _m('sinh', x)


def cosh(x):
    """MOO's ``cosh()``: hyperbolic cosine."""
    return _m('cosh', x)


def tanh(x):
    """MOO's ``tanh()``: hyperbolic tangent."""
    return _m('tanh', x)


def exp(x):
    """MOO's ``exp()``: e raised to *x*."""
    return _m('exp', x)


def log(x):
    """MOO's ``log()``: natural logarithm."""
    return _m('log', x)


def log10(x):
    """MOO's ``log10()``: base-10 logarithm."""
    return _m('log10', x)


def ceil(x):
    """MOO's ``ceil()``: round up.  Returns a float, as MOO's does."""
    import math
    return float(math.ceil(float(x)))


def trunc(x):
    """MOO's ``trunc()``: round toward zero.  Returns a float."""
    return float(int(float(x)))


def floatstr(x, precision: int = 0, scientific=False) -> str:
    """
    MOO's ``floatstr()``: format a float with a chosen precision.

    Unlike ``tostr()``, this says exactly how many digits it wants, which
    is why cores use it for money and measurements.

    Args:
        x: The number.
        precision: Digits after the point.
        scientific: Use exponential notation.

    Returns:
        str: The formatted number.
    """
    p = max(0, int(precision))
    return f'{float(x):.{p}e}' if scientific else f'{float(x):.{p}f}'


# ---------------------------------------------------------------------------
# Server measurement, and connection control
# ---------------------------------------------------------------------------

def value_bytes(value) -> int:
    """
    MOO's ``value_bytes()``: how much memory a value occupies.

    MOO reports its own internal representation; this reports Python's,
    recursing into lists and dicts so a big list does not read as the
    size of a pointer.  The number is therefore the right shape -- bigger
    things are bigger -- without being LambdaMOO's exact figure, which
    was a fact about a C struct that does not exist here.

    Args:
        value: Anything.

    Returns:
        int: Approximate size in bytes.
    """
    import sys
    seen = set()

    def size(v):
        if id(v) in seen:
            return 0
        seen.add(id(v))
        n = sys.getsizeof(v, 0)
        if isinstance(v, (list, tuple, set)):
            n += sum(size(x) for x in v)
        elif isinstance(v, dict):
            n += sum(size(k) + size(x) for k, x in v.items())
        return n

    return size(value)


def memory_usage() -> List:
    """
    MOO's ``memory_usage()``: the server's memory, in MOO's shape.

    MOO returns ``{{block-size, nused, nfree}, ...}`` for its own
    allocator.  There is no such allocator here, so this reports one
    entry describing the process as a whole rather than inventing a
    breakdown that would be fiction.

    Returns:
        list: A single ``[block-size, nused, nfree]`` entry.
    """
    try:
        import resource
        used = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:
        used = 0
    return [[1, int(used), 0]]


def dump_database() -> int:
    """
    MOO's ``dump_database()``: checkpoint the database to disk now.

    Returns:
        int: 1 on success, 0 on failure.
    """
    try:
        from .builtins import checkpoint_db
        checkpoint_db()
        return 1
    except Exception:
        logger.exception('dump_database failed')
        return 0


def task_stack(task=None, include_line_numbers=False) -> List:
    """
    MOO's ``task_stack()``: the call stack of a suspended task.

    Only the running task's stack is reachable here.  A suspended task in
    this engine is a parked thread, and its frames live on that thread --
    they are not recorded anywhere a second thread could read them.  For
    any other task this returns ``[]`` rather than a plausible-looking
    stack belonging to the wrong task.

    Args:
        task: Task id.  Omitted, or the current task, gives this stack.
        include_line_numbers: Accepted for compatibility; line numbers
            are always 0, as in :func:`~moo.builtins.callers`.

    Returns:
        list: Frames, innermost last, or ``[]``.
    """
    from .builtins import callers, task_id
    if task is None or task == task_id():
        return callers()
    return []


def function_info(name: str = None):
    """
    MOO's ``function_info()``: what builtins exist.

    MOO returns ``{{name, min-args, max-args, types}, ...}``.  Argument
    counts here come from the Python signature, and the types column is
    empty because these functions are not declared with MOO's type codes.

    Args:
        name: A single builtin to describe, or None for all of them.

    Returns:
        list: One ``[name, min_args, max_args, types]`` entry per builtin.
    """
    import inspect
    from .builtins import _get_builtin_ns_template
    ns = dict(_get_builtin_ns_template())
    ns.update({n: globals()[n] for n in __all__ if n in globals()})
    out = []
    for n, fn in sorted(ns.items()):
        if not callable(fn) or (name is not None and n != name):
            continue
        try:
            params = list(inspect.signature(fn).parameters.values())
        except (TypeError, ValueError):
            continue
        required = sum(1 for p in params
                       if p.default is p.empty and
                       p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
        variadic = any(p.kind == p.VAR_POSITIONAL for p in params)
        out.append([n, required, -1 if variadic else len(params), []])
    return out


def flush_input(who, show_messages=False) -> None:
    """
    MOO's ``flush_input()``: discard whatever *who* has typed ahead.

    Args:
        who: A player object or object number.
        show_messages: Whether to tell them, accepted for compatibility.
    """
    conn = _connection(who)
    buf = getattr(conn, 'input_buffer', None) if conn else None
    if buf is not None:
        try:
            buf.clear()
        except Exception:
            pass


def force_input(who, line: str, at_front=False) -> None:
    """
    MOO's ``force_input()``: make *who* appear to have typed *line*.

    Not implemented, and deliberately so.  It is the one builtin here
    that would let ported code act as another player -- issuing commands
    under their name, with their permissions, without their knowledge.
    That is worth more than the handful of marks it costs, so it does
    nothing and says why rather than quietly working.

    Args:
        who: A player object or object number.
        line: What they would have typed.
        at_front: Whether to jump the queue.
    """
    logger.warning('force_input(%s, %r) ignored: injecting input as another '
                   'player is not supported', who, line)


def output_delimiters(who) -> List:
    """
    MOO's ``output_delimiters()``: the prefix and suffix strings set by
    the ``PREFIX``/``SUFFIX`` out-of-band commands.

    This engine has no out-of-band command layer, so both are empty --
    which is also what MOO returns when a connection has never set them.

    Args:
        who: A player object or object number.

    Returns:
        list: ``[prefix, suffix]``.
    """
    return ['', '']


# ---------------------------------------------------------------------------
# Operators that look the same in both languages and are not
#
# These are the quietest bugs a port can have.  Nothing raises, nothing
# looks wrong, and the verb behaves correctly on most inputs -- so a
# translation carrying one of these reads as finished and is not.
#
# Each is checked against mooR's implementation rather than against
# memory: string comparison in crates/var/src/string.rs (PartialEq goes
# through cmp_case_insensitive), division and modulus in
# crates/var/src/scalar.rs (checked_div and checked_rem, which are C's).
# ---------------------------------------------------------------------------

def _fold(x):
    """Lower-case a string, leave anything else alone."""
    return x.lower() if isinstance(x, str) else x


def moo_eq(a, b) -> bool:
    """
    MOO's ``==``: **string comparison ignores case.**

    ``"Foo" == "foo"`` is true in MOO and false in Python.  This is the
    single widest silent difference between the two languages -- it
    touches roughly one clean-translating verb in eight -- because
    nothing about `x == "north"` looks wrong, and it behaves correctly
    right up until someone types "North".

    Lists compare element-wise under the same rule, since MOO's list
    equality is its scalar equality applied down the list.

    Args:
        a: Either value.
        b: The other.

    Returns:
        bool: Whether MOO would call them equal.
    """
    if isinstance(a, str) and isinstance(b, str):
        return a.lower() == b.lower()
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(moo_eq(x, y) for x, y in zip(a, b))
    return a == b


def moo_ne(a, b) -> bool:
    """MOO's ``!=``.  See :func:`moo_eq` for why this is not Python's."""
    return not moo_eq(a, b)


def moo_lt(a, b) -> bool:
    """MOO's ``<``.  Strings order case-insensitively."""
    return _fold(a) < _fold(b)


def moo_le(a, b) -> bool:
    """MOO's ``<=``.  Strings order case-insensitively."""
    return _fold(a) <= _fold(b)


def moo_gt(a, b) -> bool:
    """MOO's ``>``.  Strings order case-insensitively."""
    return _fold(a) > _fold(b)


def moo_ge(a, b) -> bool:
    """MOO's ``>=``.  Strings order case-insensitively."""
    return _fold(a) >= _fold(b)


def moo_div(a, b):
    """
    MOO's ``/``: integer division stays **integer** and truncates toward
    zero.

    Two differences from Python in one operator, and neither raises.

    Python's ``/`` on two integers produces a float, so ``7 / 2`` is
    ``3.5`` where MOO gives ``3``.  Using ``//`` instead fixes the type
    but not the rounding: Python floors, C truncates, so ``-7 / 2`` is
    ``-3`` in MOO and ``-4`` under ``//``.  The sign only shows up on
    negative operands, which is exactly when a game rule stops being
    tested.

    Args:
        a: Dividend.
        b: Divisor.

    Returns:
        An int when both operands are ints, else a float.

    Raises:
        MOOError: On division by zero, as MOO's E_INVARG.
    """
    if isinstance(a, bool):
        a = int(a)
    if isinstance(b, bool):
        b = int(b)
    if isinstance(a, int) and isinstance(b, int):
        if b == 0:
            raise MOOError('Integer division by zero')
        q = abs(a) // abs(b)
        return -q if (a < 0) != (b < 0) else q
    return a / b


def moo_mod(a, b):
    """
    MOO's ``%``: the remainder takes the sign of the **dividend**.

    Python's takes the sign of the divisor, so ``-7 % 2`` is ``-1`` in
    MOO and ``1`` in Python.  Both are defensible; they are not the same,
    and code that reaches for ``%`` on a possibly-negative number is
    usually doing something the difference breaks.

    Args:
        a: Dividend.
        b: Divisor.

    Returns:
        The remainder, with MOO's sign convention.

    Raises:
        MOOError: On division by zero.
    """
    if isinstance(a, bool):
        a = int(a)
    if isinstance(b, bool):
        b = int(b)
    if isinstance(a, int) and isinstance(b, int):
        if b == 0:
            raise MOOError('Integer division by zero')
        return a - b * moo_div(a, b)
    import math
    return math.fmod(a, b)


def moo_listset(seq, index, value):
    """
    Indexed assignment with MOO's **value** semantics: a new container.

    MOO lists are values, not references.  After ``l2 = l1; l2[1] = 5;``
    the list ``l1`` is unchanged, because the assignment built a new list
    and rebound ``l2`` to it.  Python's lists are references, so the
    obvious translation mutates in place and changes ``l1`` too -- a bug
    that only appears when something else still holds the original, which
    is to say rarely, and far from the line that caused it.

    This returns a copy for lists so the caller can rebind.  Dicts and
    objects keep reference semantics, because MOO's do as well.

    Args:
        seq: The container.
        index: An already-translated index, or a key.
        value: What to store.

    Returns:
        The updated container -- a new list, or the same dict.
    """
    if isinstance(seq, list):
        out = list(seq)
        out[index] = value
        return out
    if isinstance(seq, str):
        i = index if index >= 0 else len(seq) + index
        return seq[:i] + str(value) + seq[i + 1:]
    seq[index] = value
    return seq


# ---------------------------------------------------------------------------
# System references
#
# `$foo` is not special syntax in MOO.  It is exactly `#0.foo` -- a
# property on the system object -- and the core sets those up at build
# time.  This engine already works the same way: #0 is SystemObject and
# carries $chair, $item, $obj and the rest.
#
# So there was never anything to guess at here.  @port marked every
# unknown $reference as "point this at the right one" only because it had
# no way to look, which is odd given that it runs inside the server.
# ---------------------------------------------------------------------------

def sysobj(name: str):
    """
    Resolve MOO's ``$name`` -- the property *name* on object #0.

    Args:
        name: The reference, without the ``$``.

    Returns:
        Whatever ``#0.name`` holds, usually an object.

    Raises:
        MOOError: If #0 has no such property, which is MOO's E_PROPNF.
            Raising matters: a missing $reference that returned None would
            turn `$mail_agent:send(...)` into a call on nothing, and the
            failure would surface somewhere else entirely.
    """
    from .builtins import _database
    if _database is None:
        raise MOOError(f'${name}: no database')
    zero = _database.get_object(0)
    if zero is None:
        raise MOOError(f'${name}: no system object')
    value = getattr(zero, str(name), None)
    if value is None or repr(value) == 'None':
        raise MOOError(f'${name} is not defined on #0')
    return value


def has_sysobj(name: str) -> bool:
    """
    Whether ``$name`` resolves, without raising if it does not.

    This is what @port calls at translation time to decide between a
    clean reference and a marked one.

    Args:
        name: The reference, without the ``$``.

    Returns:
        bool: True if #0 defines it.
    """
    try:
        sysobj(name)
        return True
    except Exception:
        return False


def set_sysobj(name: str, value):
    """
    Assign MOO's ``$name`` -- that is, set the property on object #0.

    Cores do this in their setup verbs: ``$shutdown_message = "";`` is
    ordinary configuration, not a special form.  It needs its own
    function only because the read side is a call, and Python cannot
    assign to one.

    Args:
        name: The reference, without the ``$``.
        value: What to store.

    Returns:
        *value*, so this works in expression position too.

    Raises:
        MOOError: If there is no database or no #0 to store it on.
    """
    from .builtins import _database
    if _database is None:
        raise MOOError(f'${name}: no database')
    zero = _database.get_object(0)
    if zero is None:
        raise MOOError(f'${name}: no system object')
    setattr(zero, str(name), value)
    return value
