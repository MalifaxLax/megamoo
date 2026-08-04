"""
Talk to others sitting at your table or furniture.

Usage: tt <message>  |  tt :<emote>

Examples:
    tt Hello everyone!      - Say something to those at your table
    tt :smiles warmly.      - Emote to those at your table

You must be sitting at a table or furniture to use this command.
"""

cur_table = pobj.table
if not cur_table:
    pobj.msg("You aren't sitting at a table.")
    return

try:
    furn = db.get_object(cur_table)
except Exception:
    pobj.msg("You aren't sitting at a table.")
    pobj.table = None
    return

sitters = furn.sitters or []
if pobj.objnum not in sitters:
    pobj.msg("You aren't sitting at a table.")
    pobj.table = None
    return

if not args:
    pobj.msg("Say what?")
    return

# Build list of sitter objects (excluding self)
others = []
for objnum in sitters:
    if objnum != pobj.objnum:
        try:
            others.append(db.get_object(objnum))
        except Exception:
            pass

noun = getattr(furn, 'noun', 'table') or 'table'

if args[0] == ':':
    # Emote: "At your table, Name smiles"
    emote = args[1:].strip()
    msg = f"At your {noun}, {pobj.name} {emote}"
    pobj.msg(msg)
    for other in others:
        other.msg(msg)
else:
    # Speech
    pobj.msg(f'You say to those at {furn.name}, "{args}"')
    msg = f'At your {noun}, {pobj.name} says, "{args}"'
    for other in others:
        other.msg(msg)
