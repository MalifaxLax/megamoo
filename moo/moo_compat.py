"""
MOO compatibility layer.

MegaMOO reimplements the MOO *model*, not the MOO *language*: verbs are
Python.  That leaves a small set of things a LambdaMOO programmer reaches
for by reflex which have no Python equivalent, and which a mechanical port
of old MOO code will hit on almost every line.

This module supplies them:

``tell(who, ...)``
    ``player:tell("a", "b")`` concatenates its arguments and sends them to
    one player.  The MegaMOO spelling is ``pobj.msg(...)``; ``tell()`` is
    provided so ported code reads the way it was written.

``pass_(...)``
    MOO's ``pass(@args)`` calls the *same* verb on the parent object.
    ``pass`` is a reserved word in Python, hence the trailing underscore.

``E_PERM`` and friends
    In MOO, errors are first-class *values*: they can be returned, stored
    in properties, and compared with ``==``, as well as raised.  The engine
    already models this with :class:`moo.properties.MOOError`; what was
    missing was the set of named singletons.  They are defined here and
    injected into every verb namespace, so verb code can write both
    ``raise E_PERM`` and ``if result == E_PERM``.

These names are injected into every verb namespace by
:mod:`moo.verb_namespace`, the same way ``su`` and ``ou`` are, so verb code
gets them without importing anything.

See ``docs/guide/`` and the README's "Porting from LambdaMOO" section for
the wider substitution table.
"""

from .properties import MOOError

__all__ = [
    'MOO_ERRORS', 'ERROR_NAMES',
    'E_NONE', 'E_TYPE', 'E_DIV', 'E_PERM', 'E_PROPNF', 'E_VERBNF',
    'E_VARNF', 'E_INVIND', 'E_RECMOVE', 'E_MAXREC', 'E_RANGE', 'E_ARGS',
    'E_NACC', 'E_INVARG', 'E_QUOTA', 'E_FLOAT',
    'tell', 'make_pass', 'build_compat_namespace',
]


# ---------------------------------------------------------------------------
# MOO error values
# ---------------------------------------------------------------------------
#
# Codes and ordering follow the LambdaMOO Programmer's Manual, so that code
# ported from a MOO keeps the same names and the same meanings.  The numeric
# values are LambdaMOO's own, kept for round-tripping error values through
# an imported database.

_ERROR_TABLE = (
    ('E_NONE',    0,  'No error'),
    ('E_TYPE',    1,  'Type mismatch'),
    ('E_DIV',     2,  'Division by zero'),
    ('E_PERM',    3,  'Permission denied'),
    ('E_PROPNF',  4,  'Property not found'),
    ('E_VERBNF',  5,  'Verb not found'),
    ('E_VARNF',   6,  'Variable not found'),
    ('E_INVIND',  7,  'Invalid indirection'),
    ('E_RECMOVE', 8,  'Recursive move'),
    ('E_MAXREC',  9,  'Too many verb calls'),
    ('E_RANGE',   10, 'Range error'),
    ('E_ARGS',    11, 'Incorrect number of arguments'),
    ('E_NACC',    12, 'Move refused by destination'),
    ('E_INVARG',  13, 'Invalid argument'),
    ('E_QUOTA',   14, 'Resource limit exceeded'),
    ('E_FLOAT',   15, 'Floating-point arithmetic error'),
)


def _make_error(code: str, number: int, message: str) -> MOOError:
    """Build one error singleton, tagging it with its LambdaMOO number."""
    err = MOOError(code, message)
    err.number = number
    return err


#: Every MOO error value, keyed by name (``'E_PERM'`` -> the singleton).
MOO_ERRORS = {
    code: _make_error(code, number, message)
    for code, number, message in _ERROR_TABLE
}

#: Reverse lookup, LambdaMOO error number -> name.  Used when importing a
#: database that stores errors numerically.
ERROR_NAMES = {number: code for code, number, _ in _ERROR_TABLE}

# Module-level names, so engine code can ``from .moo_compat import E_PERM``.
E_NONE    = MOO_ERRORS['E_NONE']
E_TYPE    = MOO_ERRORS['E_TYPE']
E_DIV     = MOO_ERRORS['E_DIV']
E_PERM    = MOO_ERRORS['E_PERM']
E_PROPNF  = MOO_ERRORS['E_PROPNF']
E_VERBNF  = MOO_ERRORS['E_VERBNF']
E_VARNF   = MOO_ERRORS['E_VARNF']
E_INVIND  = MOO_ERRORS['E_INVIND']
E_RECMOVE = MOO_ERRORS['E_RECMOVE']
E_MAXREC  = MOO_ERRORS['E_MAXREC']
E_RANGE   = MOO_ERRORS['E_RANGE']
E_ARGS    = MOO_ERRORS['E_ARGS']
E_NACC    = MOO_ERRORS['E_NACC']
E_INVARG  = MOO_ERRORS['E_INVARG']
E_QUOTA   = MOO_ERRORS['E_QUOTA']
E_FLOAT   = MOO_ERRORS['E_FLOAT']


# ---------------------------------------------------------------------------
# tell()
# ---------------------------------------------------------------------------

def tell(who, *parts, **kwargs):
    """
    Send text to one object, MOO-style.

    ``player:tell("You have ", n, " coins.")`` in MOO concatenates its
    arguments and delivers the result as one line.  This does the same::

        tell(pobj, "You have ", n, " coins.")

    which is equivalent to the native MegaMOO spelling::

        pobj.msg(f"You have {n} coins.")

    Non-string arguments are stringified, matching MOO's behaviour of
    accepting numbers and object references inline.  A call with no parts
    sends an empty line, as ``player:tell()`` does.

    Args:
        who:      The object to notify.  Anything with a ``msg`` method.
        *parts:   Pieces to concatenate.
        **kwargs: Passed through to ``msg()``, so the substitution kwargs
                  (``sub=``, ``dob=``, ``s0=`` ...) still work.

    Returns:
        None.  MOO's ``tell`` returns no useful value either.
    """
    if who is None:
        return
    msg = who.msg if hasattr(who, 'msg') else None
    if msg is None:
        return
    msg(''.join(str(p) for p in parts), **kwargs)


# ---------------------------------------------------------------------------
# pass_()
# ---------------------------------------------------------------------------

def make_pass(this, verb_name, call_verb, db):
    """
    Build the ``pass_`` closure for one verb execution.

    MOO's ``pass(@args)`` re-invokes the *currently executing verb name* on
    the parent of the object the verb is defined on, which is how a child
    extends inherited behaviour rather than replacing it.  Python reserves
    the word ``pass``, so verb code spells it ``pass_``.

    The closure is built per-execution because it needs to know which verb
    is running and on what -- neither is knowable at import time.

    Args:
        this:      The object the verb is executing on.
        verb_name: The name of the verb currently running.
        call_verb: The namespace's own ``call_verb``, so the parent call
                   inherits the same permission and depth accounting.
        db:        Database handle, used to resolve the parent object.

    Returns:
        A callable ``pass_(*args, **kwargs)``.
    """
    def pass_(*args, **kwargs):
        """
        Call this same verb on the parent object.

        Returns the parent verb's ``result``, or ``None`` when there is no
        parent to pass to (mirroring MOO, where passing from a verb with no
        parent definition is a no-op rather than an error).
        """
        # Falsiness rather than `is None`: an unset property reads as the
        # _null_attr sentinel, which is falsy but is *not* None, and a root
        # object records its parent as 0.  Both mean "nothing to pass to".
        parent = this.parent
        if not parent:
            return None

        # A parent recorded as a bare object number still needs resolving.
        if isinstance(parent, int):
            if parent == 0:
                return None
            parent = db.get_object(parent)
            if parent is None:
                return None

        # Forward the arguments as given. This used to keep only a lone
        # string and silently drop every other shape, because call_verb
        # took an argument *string* and there was nowhere for a real
        # argument list to go -- so `pass_(a, b)` quietly became
        # `pass_()`. call_verb takes positional arguments now, so a pass
        # carries what it was given.
        return call_verb(parent, verb_name, *args,
                         this_override=this, **kwargs)

    return pass_


# ---------------------------------------------------------------------------
# Namespace assembly
# ---------------------------------------------------------------------------

def build_compat_namespace(this=None, verb_name='', call_verb=None, db=None):
    """
    Return the compatibility names to merge into a verb namespace.

    Called by :func:`moo.verb_namespace.build_verb_namespace`.  The error
    values and ``tell`` are context-free; ``pass_`` is only included when
    enough context was supplied to build it.

    Args:
        this:      Object the verb is running on.
        verb_name: Name of the running verb.
        call_verb: The namespace's ``call_verb`` callable.
        db:        Database handle.

    Returns:
        dict: Names to inject.
    """
    ns = dict(MOO_ERRORS)
    ns['tell'] = tell
    if this is not None and verb_name and call_verb is not None:
        ns['pass_'] = make_pass(this, verb_name, call_verb, db)
    return ns
