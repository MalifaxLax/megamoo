"""
on_unpuppet hook on #5 (ICharacter).

Fires automatically when the player disconnects or exits the game (before
the character is stored in #2). Cleans up furniture/table state and removes
the character from the room's plist.

Hidden:  yes
"""

# Clean up furniture/table state
table_num = this.table
if table_num:
    try:
        furn = db.get_object(table_num)
        sitters = furn.sitters
        if sitters and this.objnum in sitters:
            sitters.remove(this.objnum)
            furn.sitters = sitters
            db.save_object(furn)
    except Exception:
        pass
    this.table = None

# Remove from room plist
# Objnums, and every occurrence -- see on_puppet.  This compared a
# MOOObject against a list of ints too, so logging out never removed
# anything and the room kept counting you after you had gone.
_room = this.location
if _room and this.is_char:
    _plist = [getattr(p, 'objnum', p) for p in (_room.plist or [])]
    if this.objnum in _plist:
        _room.set_property('plist', [p for p in _plist if p != this.objnum], db)
