"""
pmatch on $match_utils.

Ported from `moo.match_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple, Union

from moo.objects import MOOObject



def pmatch(inp: str, pobj: MOOObject,
           candidates: Sequence[MOOObject]) -> Optional[MOOObject]:
    """
    Player/restricted match -- like :func:`bmatch` but without dbref support.

    This matcher is intended for use in non-wizard commands where players
    should not be able to use ``#N`` syntax to reference arbitrary
    objects.  It supports ``me``, ``here``, ``my <X>``, and name
    matching, but NOT ``#N`` or ``$name``.

    The ``my <X>`` handling differs from :func:`bmatch`:  rather than
    searching ``pobj.contents`` directly, it filters the *candidates*
    list to only include objects whose location is *pobj*.  This is
    useful when the candidates list has already been curated.

    Args:
        inp (str): Raw player input.
        pobj (MOOObject): The acting player object.
        candidates (Sequence[MOOObject]): Objects to search.

    Returns:
        MOOObject or None: The resolved object, or ``None``.
    """
    if not inp:
        return None

    text = inp.strip()

    # --- "my <X>" -- filter candidates to player's possessions ---
    if text.casefold().startswith('my '):
        text = text[3:].strip()
        if not text:
            return None
        # Filter candidates to only those located inside the player
        my_items = [obj for obj in candidates
                    if getattr(obj.location, 'objnum', None) == pobj.objnum]
        return call_verb(this, 'match', text, my_items) if my_items else None

    # --- Keywords only: "me" and "here" (no #N or $name) ---
    low = text.casefold()
    if low == 'me':
        return pobj
    if low == 'here':
        return pobj.location

    # --- Name-based matching ---
    return call_verb(this, 'match', text, candidates)


_a = kwargs.pop('_pyargs', None)

return pmatch(*(_a if _a is not None else argv), **kwargs)
