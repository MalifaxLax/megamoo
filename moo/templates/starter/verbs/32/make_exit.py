"""
make_exit on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

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

    # Movement messages, naming the direction this exit actually goes.
    #
    # Step 4 of the list above, which the body did not do.  Every exit
    # therefore inherited #14 BaseExit's literals -- "You walk out." going
    # north, south and every other way -- and an osuccess still written in
    # the %% sigil from before it moved to &, so the watching room got
    # "%%S %%OMODE out." on every move through a created exit.
    #
    # The templates have been in globals.py as ESUCC/EOSUCC/EODROP all
    # along; `&1` is the slot fname and rfname exist to fill.
    #
    # Only when there is a name to put in.  A go-exit created without one
    # keeps whatever its parent says, which is right for `go archway`:
    # there is no direction to announce.
    _fname = fname or noun
    if _fname:
        from moo.globals import ESUCC, EOSUCC, EODROP, GESUCC, GEOSUCC
        _rfname = rfname or _fname
        if fname:
            # A direction was named, so the name belongs in the sentence:
            # you go north, you do not go through north.
            _succ, _osucc = (ESUCC.replace('&1', _fname),
                             EOSUCC.replace('&1', _fname))
        else:
            # A named exit -- a door, an archway, drapes -- is a thing you
            # go through, and &d reads its name at emit time so a later
            # rename carries.  Only @open names a direction; the four
            # named-exit builders pass none, which is what tells them
            # apart here without make_exit having to know their parents.
            _succ, _osucc = GESUCC, GEOSUCC
        new_exit.add_property('success', _succ, perms='rc')
        new_exit.add_property('osuccess', _osucc, perms='rc')
        new_exit.add_property('odrop', EODROP.replace('&1', _rfname), perms='rc')

    # Set destination
    if dest:
        new_exit.add_property('destination', dest.objnum, perms='rc')

    # Place in room
    if room:
        new_exit.move_to(room, db)
        exits = room.exits or []
        exits.append(new_exit.objnum)
        room.exits = exits
        room._mark_modified()

    return new_exit


_a = kwargs.pop('_pyargs', None)

return make_exit(*(_a if _a is not None else argv), **kwargs)
