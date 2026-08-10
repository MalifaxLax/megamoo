"""
make_postatus verb on #5 (ICharacter).

Builds and returns a combined position/status string for display in room
listings. Combines the character's position string (e.g., "sitting",
"lying down") with any active status effects (e.g., "stunned", "bleeding").

Called programmatically: call_verb(char, 'make_postatus')

Returns:
    str - A parenthesized string like "(sitting/stunned)" or "(standing)"
          or "" if the character is standing with no active statuses.

Hidden:  yes
"""

position = this.position
_status = this.status
status = {k: v for k, v in _status.items()
          if (v > 0 and k != 'life') or (k == 'life' and v == 0)} if _status else {}

_pstrings = this.position_strings
pstring = _pstrings[position] if _pstrings and position < len(_pstrings) else ''
if pstring:
    pstring = su.esub(pstring, sub=this)
sstring = ', '.join(status.keys())

if position and status:
    return f"({pstring}/{sstring})"
elif position:
    return f"({pstring})"
elif status:
    return f"({sstring})"
else:
    return ''
