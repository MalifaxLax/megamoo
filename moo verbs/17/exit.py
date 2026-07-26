"""
Leave the game world and return to the lobby.

Usage: exit  |  x
"""

ochar_num = getattr(pobj, 'account', None)
if not ochar_num:
    pobj.msg("You have no account to return to.")
    result = True
    return

if type(ochar_num) != int:
    ochar_num = ochar_num.objnum if hasattr(ochar_num, 'objnum') else int(ochar_num)

ochar = db.get_object(ochar_num)

yield 1

# Announce departure from IC room
if not getattr(pobj, 'invis', False):
    pobj.location.msg_room(f"{pobj.noun} fades from existence.", exclude=[pobj])

puppet(ochar)
result = True
return
