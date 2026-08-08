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
"""

pstring = this.position_strings[this.position]
if args == 'first':
    pstring = pstring.replace('&pp', 'your')
return pstring
