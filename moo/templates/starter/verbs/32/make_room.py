"""
make_room on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

from typing import TYPE_CHECKING, Optional



def make_room(parent: 'MOOObject', db: 'Database', pobj: 'MOOObject',
              name: Optional[str] = None) -> 'MOOObject':
    """
    Create a new room as a child of *parent*.

    Rooms are simpler than regular objects: they don't use the
    name_mod_list system.  The room name is set directly as both
    the ``noun`` and ``name`` properties.

    Room parent objects are defined in ``globals.py``:

    ===========  =======  ==================
    Type key     ObjNum   Description
    ===========  =======  ==================
    ``'room'``   #15      BaseRoom
    ``'ooc'``    #16      OOCRoom (out-of-character)
    ``'ic'``     #17      ICRoom (in-character)
    ===========  =======  ==================

    Args:
        parent: The room-type parent to inherit from (e.g. #15, #16, #17).
        db:     The database instance.
        pobj:   The player creating the room (becomes the owner).
        name:   Optional name for the room.  If omitted, the parent's
                noun is used as a default.

    Returns:
        The newly created room MOOObject.

    Examples::

        # Create an IC room named "Town Square"
        room = make_room(db.get_object(17), db, pobj, name='Town Square')

        # Create an OOC room with the default name from the parent
        lounge = make_room(db.get_object(16), db, pobj)
    """
    room_name = name if name else parent.noun
    new_room = call_verb(this, 'make_object', parent, db, pobj, noun=room_name)
    new_room.name = room_name
    return new_room


_a = kwargs.pop('_pyargs', None)

return make_room(*(_a if _a is not None else argv), **kwargs)
