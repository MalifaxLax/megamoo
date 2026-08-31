"""
Returns the character's current position string (e.g., "standing",
"sitting", "lying down") from the position_strings list, indexed by
the character's current position value.

    call_verb(char, 'postring', args='first') for first-person form.

Arguments:
    args - If 'first', substitutes '&pp' with 'your' for first-person
           perspective. Otherwise returns third-person form.

Hidden:  yes
"""

_pstrings = this.position_strings or []
_position = this.position or 0
pstring = _pstrings[_position] if 0 <= _position < len(_pstrings) else ''
if args == 'first':
    pstring = pstring.replace('&pp', 'your')
return pstring
