"""
bmatch on $match_utils.

Ported from `moo.match_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple, Union

from moo.objects import MOOObject

from moo.database import Database



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

    # --- "my <X>" -- restrict to player's own inventory ---
    if text.casefold().startswith('my '):
        text = text[3:].strip()
        return call_verb(this, 'match', text, pobj.contents) if text else None

    # --- Keywords / dbrefs / system constants ---
    obj = call_verb(this, 'omatch', text, pobj, db)
    if obj is not None:
        return obj

    # --- Name-based matching against the candidate list ---
    return call_verb(this, 'match', text, candidates)


_a = kwargs.pop('_pyargs', None)

return bmatch(*(_a if _a is not None else argv), **kwargs)
