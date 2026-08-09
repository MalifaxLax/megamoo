"""
exit verb on #5 (ICharacter).

Returns the player from the in-character (IC) world to the out-of-character
(OOC) lobby by puppeting back to their OCharacter account object.

Usage: exit  |  x

Announces the character's departure to the room (unless invisible),
then puppets the player into their OOC account character. Includes a
1-second yield delay before the puppet switch.

Note: Also defined on #17 (ICRoom) as a duplicate for IC room context.

Aliases: x
Abbrev:  exit=2
"""

ochar_num = pobj.account
if not ochar_num:
    pobj.msg("You have no account to return to.")
    result = True
    return

if type(ochar_num) != int:
    ochar_num = ochar_num.objnum if hasattr(ochar_num, 'objnum') else int(ochar_num)

ochar = db.get_object(ochar_num)

yield 1

# Announce departure from IC room
if not pobj.invis:
    pobj.location.msg_room(f"{pobj.noun} fades from existence.", exclude=[pobj])

puppet(ochar)
result = True
return
