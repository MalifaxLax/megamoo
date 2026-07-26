"""
look_ verb on #30 (BaseFurniture).

Displays the furniture's name, description, and lists any characters
currently sitting or lying on it. Shows each occupant's position
string and the furniture's sit_prep (e.g., "on", "at", "in").

Called by the look verb: call_verb(furniture, 'look_')

Cleans stale sitters (characters no longer in the room) before display.

Returns True to indicate the action was handled.
"""

item = this
desc = getattr(item, 'description', None)

pobj.msg(f"\n{item.name}")
if desc:
    pobj.msg(desc)

# Show occupants
sitters = getattr(item, 'sitters', None) or []
if sitters and pobj.location:
    here = [obj.objnum for obj in pobj.location.contents]
    sitters = [s for s in sitters if s in here]
    item.sitters = sitters

    for objnum in sitters:
        try:
            char = db.get_object(objnum)
            pos = getattr(char, 'position', 0) or 0
            pstrings = getattr(char, 'position_strings', None) or []
            if pos < len(pstrings):
                pstring = pstrings[pos]
            elif pos == 6:
                pstring = 'sitting'
            elif pos >= 7:
                pstring = 'lying'
            else:
                pstring = 'here'
            prep = getattr(item, 'sit_prep', 'on')
            pobj.msg(f"{char.cname} is {pstring} {prep} it.")
        except Exception:
            pass

return True
