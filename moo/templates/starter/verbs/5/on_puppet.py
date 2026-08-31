"""
on_puppet on #5 (ICharacter)
Called after character is moved to last_location on login/puppet.
Adds this character to the room's plist.

Hidden:  yes
"""

_room = this.location
if _room and this.is_char:
    _plist = [getattr(p, 'objnum', p) for p in (_room.plist or [])]
    if this.objnum not in _plist:
        _plist.append(this.objnum)
    _room.set_property('plist', _plist, db)
