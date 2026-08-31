"""
Pick up an item from the ground or take it from a container.

Usage: get <item>
       get <item> from <container>
       get <item> from off|under|behind <container>

Examples:
    get sword           - Pick up a sword from the ground
    get coin from chest - Take a coin from inside a chest
    get key from under mat - Get a key from under something
"""

if not args:
    pobj.msg("Get what?")
    return

if pobj.do_wait():
    return

if prep:
    dispatch = None
    if prep.startswith('from off') or prep == 'off':
        dispatch = 'on_get'
    elif prep.startswith('from und') or prep.startswith('from ben'):
        dispatch = 'under_get'
    elif prep.startswith('from beh'):
        dispatch = 'behind_get'
    elif prep == 'from' or prep.startswith('from ato') or prep.startswith('out'):
        dispatch = 'in_get'

    if dispatch and iobj:
        candidates = list(pobj.location.contents) + list(pobj.contents)
        container = pmatch(iobj, pobj, candidates)
        if not container:
            pobj.msg("From where?")
            return
        if dispatch == 'in_get':
            in_raw = container.in_contents or []
            on_raw = container.on_contents or []
            if in_raw:
                dispatch = 'in_get'
            elif on_raw:
                dispatch = 'on_get'
        try:
            call_verb(container, dispatch, dobj=dobj)
        except KeyError:
            pobj.msg("You can't get anything from that.")
        return

item = pmatch(dobj, pobj, list(pobj.location.contents))
if not item:
    pobj.msg("Get what?")
    return

if item.is_exit:
    pobj.msg("Get what?")
    return

if item.is_char:
    pobj.msg("&D probably wouldn't appreciate that.", dob=item)
    return

free = call_verb(pobj, 'hands_free')
item_hands = (item.hands or 1)
if not free:
    pobj.msg("Your hands are full.")
    return
if item_hands == 2 and free != 'both':
    pobj.msg("You need both hands free for that.")
    return

item_weight = item.weight or 0
cur_load = pobj.load or 0
max_load = getattr(pobj, 'max_load', None) or 0
if max_load and cur_load + item_weight > max_load:
    pobj.msg("You can't pick up anything else right now.")
    return

try:
    if call_verb(item, 'get_'):
        return
except KeyError:
    pass

move(item, pobj)

call_verb(pobj, 'move_to_hand', dobj=item)

pobj.load = cur_load + item_weight

pobj.msg("You pick up &d.", dob=item)
if not pobj.invis:
    pobj.location.msg_room("&S picks up &d.", exclude=[pobj], sub=pobj, dob=item)
