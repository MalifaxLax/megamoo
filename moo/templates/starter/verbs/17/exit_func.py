"""
exit_func on #17 (ICRoom)
Called when an object leaves this room.
args = objnum string of the departing object.
Removes characters from this room's plist.

Removes *every* occurrence, not the first.  See enter_func: the pair of
them appended on each arrival and removed on none, so rooms in a world
that has been played hold long runs of the same player.  Stripping all
copies here means those rooms heal themselves the next time each player
walks out.

Hidden:  yes
"""

_objnum = int(args) if args else None
if _objnum:
    _obj = db.get_object(_objnum)
    if _obj.is_char:
        _plist = list(this.plist or [])
        _plist = [getattr(p, 'objnum', p) for p in _plist]
        if _objnum in _plist:
            _plist = [p for p in _plist if p != _objnum]
            this.set_property('plist', _plist, db)
