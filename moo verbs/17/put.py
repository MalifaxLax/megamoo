"""
Place an item in, on, under, or behind something.

Usage: put <item> in|on|under|behind <object>

Examples:
    put coin in chest       - Put a coin inside a chest
    put cup on table        - Place a cup on a table
    put key under mat       - Hide a key under a mat
    put note behind shelf   - Tuck a note behind a shelf
"""

if not args:
    pobj.msg("Put what?")
    return

# RT check
if (getattr(pobj, 'rt', None) or 0) > 0:
    pobj.msg("You must wait.")
    return

if not prep:
    pobj.msg("Put it where?")
    return

# Determine dispatch verb based on preposition
dispatch = None
if smatch('into', prep, 2) or smatch('inside', prep, 2) or prep == 'in':
    dispatch = 'in_put'
elif smatch('onto', prep, 2) or smatch('upon', prep, 2) or prep == 'on':
    dispatch = 'on_put'
elif smatch('under', prep, 2) or smatch('beneath', prep, 3):
    dispatch = 'under_put'
elif smatch('behind', prep, 3):
    dispatch = 'behind_put'

if not dispatch:
    pobj.msg("Put it where?")
    return

if not dobj:
    pobj.msg("Put what?")
    return

if not iobj:
    pobj.msg("Put it where?")
    return

# Find the item in player's hands/inventory
item = pmatch(dobj, pobj, list(pobj.contents))
if not item:
    pobj.msg("You don't have that.")
    return

# Find the container in room or inventory
candidates = list(pobj.location.contents) + list(pobj.contents)
container = pmatch(iobj, pobj, candidates)
if not container:
    pobj.msg("You don't see that here.")
    return

# Dispatch to container verb
try:
    if not call_verb(container, dispatch, dobj=item):
        pobj.msg("You can't do that.")
except KeyError:
    pobj.msg("You can't put anything there.")
