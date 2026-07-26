# @windup — spawn a monster from a template and start its AI
# Usage: @windup <template> [at <room>]
# If no room given, spawns in pobj.location.
# Clones the template, copies properties, clones weapons, places in room, starts AI.

if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

if not args:
    pobj.msg('Usage: @windup <template> [at <room>]')
    return

# Parse args: split on ' at ' for optional room
parts = args.strip()
room_target = None
if ' at ' in parts:
    template_str, room_str = parts.split(' at ', 1)
    template_str = template_str.strip()
    room_str = room_str.strip()
    room_target = bmatch(room_str, pobj, [], db)
    if not room_target:
        pobj.msg(f"Room '{room_str}' not found.")
        return
else:
    template_str = parts

# Resolve template
template = bmatch(template_str, pobj, [], db)
if not template:
    pobj.msg(f"Template '{template_str}' not found.")
    return

# Verify it's a critter (parented from #800)
parent_chain = []
check = template
while check:
    parent_chain.append(check.objnum)
    p = check.parent
    if p is None:
        break
    check = db.get_object(p) if isinstance(p, int) else p
    if check and check.objnum in parent_chain:
        break

if 800 not in parent_chain:
    pobj.msg(f"#{template.objnum} is not a Critter template (not descended from #800).")
    return

# Determine spawn room
room = room_target or pobj.location
if not room:
    pobj.msg("No valid room to spawn in.")
    return

def _w(o, p, v):
    # Ungated write: set_property (add_property if the prop is new) skips the
    # safe_setattr() gate, which silently dropped the template's own props when
    # a non-wizard GM cloned a #0-owned monster -- leaving it under-configured.
    try:
        o.set_property(p, v)
    except Exception:
        o.add_property(p, v)

# Clone the template
monster = create(template.parent, 0)

# Copy properties from template
for prop_name, prop_data in template.properties.items():
    val = prop_data.value if hasattr(prop_data, 'value') else prop_data
    _w(monster, prop_name, val)

# Copy noun/aliases
monster.noun = template.noun
monster.aliases = list(template.aliases) if template.aliases else []

# Clone weapons from template
template_weapons = getattr(template, 'weapons', []) or []
new_weapons = []
for tw_num in template_weapons:
    tw = db.get_object(tw_num)
    if not tw:
        continue
    w = create(tw.parent, 0)
    for prop_name, prop_data in tw.properties.items():
        val = prop_data.value if hasattr(prop_data, 'value') else prop_data
        _w(w, prop_name, val)
    w.noun = tw.noun
    w.aliases = list(tw.aliases) if tw.aliases else []
    move(w, monster)
    new_weapons.append(w.objnum)
monster.weapons = new_weapons

# Place monster in room
move(monster, room)
monster.home_room = room.objnum

# Wind up the AI
call_verb(monster, 'wind_up')

# Show arrival emit
emits = getattr(monster, 'emits', []) or []
if emits:
    msg_room(room, emits[0])

pobj.msg(f"Spawned %<245>#{monster.objnum}:{monster.name}%n in %<245>#{room.objnum}:{room.name}%n.")
