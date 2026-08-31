"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple, Union

from moo.objects import MOOObject

def adj_match(adjectives: List[str], obj: MOOObject) -> bool:
    """
    Check whether all given adjectives appear in *obj*'s name, in order.

    This is used to disambiguate between multiple objects that share the
    same noun.  For example, if a room contains "a big blue ball" and
    "a small red ball", the adjectives ["blue"] would match the first
    but not the second.

    The matching works in two passes:

    **Pass 1 -- Name scanning (fast path)**:
        Each adjective is searched for as a whole word in ``obj.name``,
        in order.  "In order" means each adjective must appear *after*
        the previous one in the name string.  Word boundaries are
        enforced (so "blue" does not match inside "blueberry").

    **Pass 2 -- Property fallback**:
        If name scanning fails, the function checks for an ``adjectives``
        property on the object (a list of strings).  Adjectives are
        matched by prefix against this list, also in order.

    An empty adjective list always matches (returns ``True``).

    Args:
        adjectives (list of str): Adjective tokens from player input,
            in the order they were typed.
        obj (MOOObject): The candidate game object.

    Returns:
        bool: ``True`` if all adjectives match in order, ``False``
        otherwise.

    Examples::

        adj_match(['blue'], obj_named_"a big blue ball")      # True
        adj_match(['big', 'blue'], obj_named_"a big blue ball")  # True
        adj_match(['blue', 'big'], obj_named_"a big blue ball")  # False (wrong order)
    """
    if not adjectives:
        return True

    title = obj.name.casefold()

    pos = 0
    for adj in adjectives:
        adj_low = adj.casefold()
        idx = title.find(adj_low, pos)
        if idx == -1:
            break
        if idx > 0 and title[idx - 1] != ' ':
            idx = title.find(' ' + adj_low, pos)
            if idx == -1:
                break
            idx += 1
        pos = idx + len(adj_low)
    else:
        return True

    props = obj.properties
    if 'adjectives' in props:
        obj_adjs = props['adjectives'].value
        if isinstance(obj_adjs, (list, tuple)):
            obj_adjs_low = [a.casefold() for a in obj_adjs]
            last_idx = -1
            for adj in adjectives:
                adj_low = adj.casefold()
                found = False
                for i in range(last_idx + 1, len(obj_adjs_low)):
                    if obj_adjs_low[i].startswith(adj_low):
                        last_idx = i
                        found = True
                        break
                if not found:
                    return False
            return True

    return False

_a = kwargs.pop('_pyargs', None)

return adj_match(*(_a if _a is not None else argv), **kwargs)
