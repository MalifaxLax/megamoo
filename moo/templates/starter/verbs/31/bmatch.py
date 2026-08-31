"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple, Union

from moo.database import Database

from moo.objects import MOOObject

def bmatch(inp: str, pobj: MOOObject, candidates: Sequence[MOOObject],
           db: Database = None) -> Optional[MOOObject]:
    """
    Broad match -- the standard entry point for verb code.

    This is the function most verbs call to resolve a player's input
    to a game object.  It tries multiple resolution strategies in order:

    Resolution order:
        1. **Possessive**: ``my <X>`` restricts the search to the
           player's own inventory (``pobj.contents``), ignoring the
           *candidates* list entirely.
        2. **Keywords / dbrefs / constants**: Delegates to :func:`omatch`
           to handle ``me``, ``here``, ``#N``, and ``$name``.
        3. **Name matching**: Falls through to :func:`match` against
           the provided *candidates* list.

    Args:
        inp (str): Raw player input (e.g. ``"my blue sword"``,
            ``"#3"``, ``"the golden key"``).
        pobj (MOOObject): The acting player object.
        candidates (Sequence[MOOObject]): Objects to search for
            name-based matching.  Typically built from the contents
            of the player's location and/or inventory.
        db (Database, optional): Database for ``#N`` dbref resolution.
            If not provided, ``pobj._database`` is used as a fallback.

    Returns:
        MOOObject or None: The resolved object, or ``None`` if nothing
        matched.

    Examples::

        # Search room + inventory for "sword"
        bmatch("sword", pobj, pobj.contents + pobj.location.contents)

        # Search inside a specific container
        bmatch("gem", pobj, chest.contents)

        # Force inventory-only search
        bmatch("my key", pobj, [])  # 'my' prefix ignores candidates list
    """
    if not inp:
        return None

    text = inp.strip()

    if text.casefold().startswith('my '):
        text = text[3:].strip()
        return call_verb(this, 'match', text, pobj.contents) if text else None

    obj = call_verb(this, 'omatch', text, pobj, db)
    if obj is not None:
        return obj

    return call_verb(this, 'match', text, candidates)

_a = kwargs.pop('_pyargs', None)

return bmatch(*(_a if _a is not None else argv), **kwargs)
