"""
Eat something edible.

Usage: eat <item>

Examples:
    eat bread       - Eat some bread
    eat apple       - Eat an apple
    eat bowl        - Eat from a bowl of soup
"""

if not args:
    pobj.msg("Eat what?")
    return

# RT check
if not call_verb(pobj, 'time_ok'):
    return

# Match item in hands + inventory + room contents
mh = pobj.mh
oh = pobj.oh
slist = [x for x in [mh, oh] if x and hasattr(x, 'objnum')]
slist += list(pobj.location.contents) + list(pobj.contents)
item = pmatch(dobj, pobj, slist)

if not item:
    pobj.msg("Eat what?")
    return

# Try container eat first (edible liquid in a vessel), then direct edible
try:
    if call_verb(item, 'ceat'):
        return
except KeyError:
    pass

try:
    if call_verb(item, 'eat_'):
        return
except KeyError:
    pass

pobj.msg("You can't eat that!")
