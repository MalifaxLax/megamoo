# on_puppet on #5 (ICharacter)
# Called after character is moved to last_location on login/puppet.
# Adds this character to the room's plist.

_room = this.location
if _room and getattr(this, 'is_char', False):
    _plist = getattr(_room, 'plist', None) or []
    if this not in _plist:
        _plist.append(this)
        _room.set_property('plist', _plist, db)
