"""
enter_func on #13 (ICRoom)
Called when an object enters this room.
args = objnum string of the arriving object.
Appends characters to this room's plist.

In objnums, not objects.  An object reference stored inside a list is
serialised as its objnum, so `this.plist` reads back as [201, 209] --
and the old `if _obj not in _plist` compared a MOOObject against a list
of ints, never matched, and appended on every single arrival.  Its
opposite number in exit_func never matched either, so nothing was ever
removed.  A room a player had walked through forty times listed them
forty times.

Hidden:  yes
"""

_objnum = int(args) if args else None
if _objnum:
    _obj = db.get_object(_objnum)
    if _obj.is_char:
        _plist = list(this.plist or [])
        _plist = [getattr(p, 'objnum', p) for p in _plist]
        if _objnum not in _plist:
            _plist.append(_objnum)
        this.set_property('plist', _plist, db)
