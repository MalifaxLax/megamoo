"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from moo.database import Database

from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple, Union

from moo.objects import MOOObject

def _resolve_db(pobj: MOOObject, db: Database = None) -> Optional[Database]:
    """
    Obtain a Database reference from an explicit parameter or the player object.

    This helper centralises database discovery so that callers can either
    pass ``db`` explicitly or let it be found via ``pobj._database``
    (which is set when the object is loaded from the database).

    Args:
        pobj (MOOObject): The player object (may have ``_database`` set).
        db (Database, optional): An explicit database reference.  If
            provided, this takes priority.

    Returns:
        Database or None: The resolved database, or ``None`` if neither
        source provides one.
    """
    if db is not None:
        return db
    return getattr(pobj, '_database', None)

def omatch(inp: str, pobj: MOOObject, db: Database = None) -> Optional[MOOObject]:
    """
    Resolve a keyword or object reference to a game object.

    This function handles the "special" input forms that bypass normal
    name matching:

    - ``me`` -- Returns the player object (*pobj*) itself.
    - ``here`` -- Returns the player's current location (``pobj.location``).
    - ``#N`` -- Direct database lookup by object number (requires a
      ``Database`` instance).
    - ``$name`` -- System constant lookup.  Reads the property *name*
      from object #0 (the system object) and resolves it to a game
      object.  For example, ``$room_builder`` might resolve to object
      #47.

    Args:
        inp (str): The raw input string to resolve.
        pobj (MOOObject): The acting player object.
        db (Database, optional): Database for ``#N`` and ``$name``
            lookups.  If not provided, ``pobj._database`` is used.

    Returns:
        MOOObject or None: The resolved object, or ``None`` if the
        input does not match any keyword or reference pattern.

    Note:
        This function returns ``None`` for ordinary object names like
        ``"sword"`` -- those are handled by ``match()`` instead.
    """
    low = inp.casefold().strip()

    if low == 'me':
        return pobj

    if low == 'here':
        return pobj.location

    if low.startswith('#') and low[1:].isdigit():
        rdb = _resolve_db(pobj, db)
        if rdb:
            try:
                return rdb.get_object(int(low[1:]))
            except (KeyError, Exception):
                return None
        return None

    if low.startswith('$') and len(low) > 1:
        rdb = _resolve_db(pobj, db)
        if not rdb:
            return None
        prop_name = low[1:]
        try:
            sys_obj = rdb.get_object(0)
            val = getattr(sys_obj, prop_name, None)
            if val is None:
                return None
            if hasattr(val, 'objnum'):
                return val
            if isinstance(val, int):
                return rdb.get_object(val)
        except (KeyError, Exception):
            return None
        return None

    return None

_a = kwargs.pop('_pyargs', None)

return omatch(*(_a if _a is not None else argv), **kwargs)
