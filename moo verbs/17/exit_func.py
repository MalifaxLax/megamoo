# exit_func on #17 (ICRoom)
# Called when an object leaves this room.
# args = objnum string of the departing object.
# Removes characters from this room's plist.

_objnum = int(args) if args else None
if _objnum:
    _obj = db.get_object(_objnum)
    if getattr(_obj, 'is_char', False):
        _plist = getattr(this, 'plist', None) or []
        if _obj in _plist:
            _plist.remove(_obj)
            this.set_property('plist', _plist, db)
