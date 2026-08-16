"""
postring verb on #5 (ICharacter).

Returns the character's current position string (e.g., "standing",
"sitting", "lying down") from the position_strings list, indexed by
the character's current position value.

Called programmatically: call_verb(char, 'postring') or
    call_verb(char, 'postring', args='first') for first-person form.

Arguments:
    args - If 'first', substitutes '&pp' with 'your' for first-person
           perspective. Otherwise returns third-person form.

Returns:
    str - The position string for the character's current position.

Hidden:  yes
"""

# Bounds-checked, the way make_postatus guards the identical access.
#
# `position_strings` holds ten entries and `position` is only ever 0, 6 or
# 8 today, so this cannot miss -- but the two readers of the same table
# disagreed about whether it could, and the unguarded one raises where the
# other degrades. A world adding an eleventh position (a combat "knocked
# down" at 10) without extending the list would take `look` out for that
# character, while make_postatus carried on returning ''.
_pstrings = this.position_strings or []
_position = this.position or 0
pstring = _pstrings[_position] if 0 <= _position < len(_pstrings) else ''
if args == 'first':
    pstring = pstring.replace('&pp', 'your')
return pstring
