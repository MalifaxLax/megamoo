"""
on_puppet on #5 (ICharacter)
Called after character is moved to last_location on login/puppet.
Adds this character to the room's plist.

Hidden:  yes
"""

# In objnums, not objects -- the same fix as #17's enter_func/exit_func.
# A reference stored inside a list is serialised as its objnum, so plist
# reads back as [201, 209]; `if this not in _plist` compared a MOOObject
# against a list of ints, never matched, and appended on every login.
_room = this.location
if _room and this.is_char:
    _plist = [getattr(p, 'objnum', p) for p in (_room.plist or [])]
    if this.objnum not in _plist:
        _plist.append(this.objnum)
    _room.set_property('plist', _plist, db)
