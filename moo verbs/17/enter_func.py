# enter_func on #17 (ICRoom)
# Called when an object enters this room.
# args = objnum string of the arriving object.
# Appends characters to this room's plist.

_objnum = int(args) if args else None
if _objnum:
    _obj = db.get_object(_objnum)
    if _obj.is_char:
        _plist = this.plist or []
        if _obj not in _plist:
            _plist.append(_obj)
            this.set_property('plist', _plist, db)
