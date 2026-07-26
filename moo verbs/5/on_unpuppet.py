"""
on_unpuppet hook on #5 (ICharacter).

Fires automatically when the player disconnects or exits the game (before
the character is stored in #2). Cleans up furniture/table state and removes
the character from the room's plist.
"""

# Clean up furniture/table state
table_num = getattr(this, 'table', None)
if table_num:
    try:
        furn = db.get_object(table_num)
        sitters = getattr(furn, 'sitters', None)
        if sitters and this.objnum in sitters:
            sitters.remove(this.objnum)
            furn.sitters = sitters
            db.save_object(furn)
    except Exception:
        pass
    this.table = None

# Remove from room plist
_room = this.location
if _room and getattr(this, 'is_char', False):
    _plist = getattr(_room, 'plist', None) or []
    if this in _plist:
        _plist.remove(this)
        _room.set_property('plist', _plist, db)
