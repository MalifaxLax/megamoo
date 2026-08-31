"""
Displays the furniture's description, then anyone else sitting or lying
on it -- "Sinda is sitting there." The looker is left out: they know
where they are sitting.

Cleans stale sitters (characters no longer in the room) before display.

Returns True to indicate the action was handled.

Hidden:  yes
"""

item = this
desc = item.description

pobj.msg(desc if desc else "You see nothing special.")

sitters = item.sitters or []
if sitters and pobj.location:
    here = [obj.objnum for obj in pobj.location.contents]
    sitters = [s for s in sitters if s in here]
    item.sitters = sitters

    groups = {}
    for objnum in sitters:
        if objnum == pobj.objnum:
            continue
        try:
            char = db.get_object(objnum)
            pos = char.position or 0
            pstrings = char.position_strings or []
            if pos < len(pstrings):
                pstring = pstrings[pos]
            elif pos == 6:
                pstring = 'sitting'
            elif pos >= 7:
                pstring = 'lying'
            else:
                pstring = 'here'
            pstring = su.esub(pstring, sub=char)
            groups.setdefault(pstring, []).append(su.capitalise(char.name))
        except Exception:
            pass

    prep = (item.sit_prep or 'on')
    for pstring, names in groups.items():
        verb = 'is' if len(names) == 1 else 'are'
        pobj.msg(f"{su.listtoenglish(names)} {verb} {pstring} {prep} &d.",
                 dob=item)

return True
