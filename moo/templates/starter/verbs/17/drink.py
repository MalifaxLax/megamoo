"""
Take a drink from something.

Usage: drink <item>  |  sip <item>

Examples:
    drink water     - Drink some water
    sip tea         - Sip from a cup of tea
"""

if not args:
    pobj.msg("Drink what?")
    return

# RT check
if not call_verb(pobj, 'time_ok'):
    return

# Match item in hands + inventory + room contents
mh = pobj.mh
oh = pobj.oh
slist = list(pobj.location.contents)
slist += [x for x in [mh, oh] if x and hasattr(x, 'objnum')]
slist += list(pobj.contents)
item = pmatch(dobj, pobj, slist)

if not item:
    pobj.msg("Drink what?")
    return

# Try cup container drink first, then direct drinkable
try:
    if call_verb(item, 'cdrink'):
        return
except KeyError:
    pass

try:
    if call_verb(item, 'drink_'):
        return
except KeyError:
    pass

pobj.msg("You can't drink that!")
