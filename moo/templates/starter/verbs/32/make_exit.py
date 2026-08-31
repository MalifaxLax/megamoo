"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import TYPE_CHECKING, Optional

def make_exit(parent: 'MOOObject', db: 'Database', pobj: 'MOOObject',
              noun: Optional[str] = None,
              room: Optional['MOOObject'] = None,
              dest: Optional['MOOObject'] = None,
              fname: Optional[str] = None,
              rfname: Optional[str] = None) -> 'MOOObject':
    """
    Create a new exit as a child of *parent* and place it in *room*.

    Handles:
    1. Creating the exit object via make_object.
    2. Setting the destination property.
    3. Moving the exit into the room and adding it to the room's exits list.
    4. Setting default success/osuccess/odrop messages using fname/rfname.

    Args:
        parent: The exit parent object (#14, #15, #16, #17, etc.).
        db:     The database instance.
        pobj:   The player creating the exit.
        noun:   The exit's noun (e.g. 'north', 'door', 'gate').
        room:   The room to place the exit in.
        dest:   Optional destination room.
        fname:  Full direction name for messages (e.g. 'north'). Defaults to noun.
        rfname: Reverse full name for arrival messages (e.g. 'the south'). Defaults to fname.

    Returns:
        The newly created exit MOOObject.
    """
    new_exit = call_verb(this, 'make_object', parent, db, pobj, noun=noun)

    _fname = fname or noun
    if _fname:
        from moo.globals import ESUCC, EOSUCC, EODROP, GESUCC, GEOSUCC
        _rfname = rfname or _fname
        if fname:
            _succ, _osucc = (ESUCC.replace('&1', _fname),
                             EOSUCC.replace('&1', _fname))
        else:
            _succ, _osucc = GESUCC, GEOSUCC
        new_exit.add_property('success', _succ, perms='rc')
        new_exit.add_property('osuccess', _osucc, perms='rc')
        new_exit.add_property('odrop', EODROP.replace('&1', _rfname), perms='rc')

    if dest:
        new_exit.add_property('destination', dest.objnum, perms='rc')

    if room:
        new_exit.move_to(room, db)
        exits = room.exits or []
        exits.append(new_exit.objnum)
        room.exits = exits
        room._mark_modified()

    return new_exit

_a = kwargs.pop('_pyargs', None)

return make_exit(*(_a if _a is not None else argv), **kwargs)
