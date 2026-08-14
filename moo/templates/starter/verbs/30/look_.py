"""
look_ verb on #30 (BaseFurniture).

Displays the furniture's description, then anyone else sitting or lying
on it -- "Sinda is sitting there." The looker is left out: they know
where they are sitting.

Called by the look verb: call_verb(furniture, 'look_')

Cleans stale sitters (characters no longer in the room) before display.

Returns True to indicate the action was handled.

Hidden:  yes
"""

item = this
desc = item.description

# The description alone, no name header -- the same as #17:look and
# #26:look_, which this hook returns before and would otherwise
# contradict.  No leading blank either: that newline belonged to the
# header line, and with the header gone it was a gap above nothing,
# which object-look had and character-look did not.
pobj.msg(desc if desc else "You see nothing special.")

# Show occupants
sitters = item.sitters or []
if sitters and pobj.location:
    here = [obj.objnum for obj in pobj.location.contents]
    sitters = [s for s in sitters if s in here]
    item.sitters = sitters

    # Grouped by position, so several people at one table read as a
    # sentence -- "Sinda and Niclas are sitting at a rosewood table." --
    # rather than as a line each.  Grouped by *position* and not simply
    # all together, because someone lying down must not be described as
    # sitting alongside them.
    groups = {}
    for objnum in sitters:
        # Not yourself: you are the one looking, and you know where you
        # are sitting.  #15:look_here leaves the looker out of its
        # furniture line for the same reason.
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
            # esub here, as #15:look_here does: the position strings carry
            # pronouns -- 'lying on &pp back' -- and printed raw the sigil
            # reaches the player.  Per character, since the pronoun is
            # theirs, before they are grouped by the result.
            pstring = su.esub(pstring, sub=char)
            groups.setdefault(pstring, []).append(su.capitalise(char.name))
        except Exception:
            pass

    prep = (item.sit_prep or 'on')
    for pstring, names in groups.items():
        # &d rather than the name inline, so the furniture is substituted
        # the way every other message in the world names an object.
        verb = 'is' if len(names) == 1 else 'are'
        pobj.msg(f"{su.listtoenglish(names)} {verb} {pstring} {prep} &d.",
                 dob=item)

return True
