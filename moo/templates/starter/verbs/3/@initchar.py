"""
Sets all missing ICharacter properties (hand, mh, oh, load, desclist,
rt, position, and the resource pools) on an existing character. Use
this to retroactively initialize characters created before chargen
added these properties.

Usage: @initchar <target>

Arguments:
    target  - The character to initialize (matched in room and inventory).

Auth: gm3+ (auth_level 3)

Note: Only adds properties that are not already defined on the target.
Reports which properties were added and which were already present.
"""

if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

spec = args.strip() if args else ''
if not spec:
    pobj.msg('Usage: @initchar <target>')
    pobj.msg('Example: @initchar me')
    pobj.msg('Example: @initchar #52')
    return

candidates = list(pobj.location.contents) + list(pobj.contents)
target = bmatch(spec, pobj, candidates, db)
if not target:
    pobj.msg(f"Target '{spec}' not found.")
    return

props = {
    'hand': ['right', 'left'],
    'mh': None,
    'oh': None,
    'load': 0,

    'desclist': ['', '', '', ''],
    'gender': None,
    'last_name': None,
    'chargen_step': None,
    'level': 1,

    'position': 0,
    'rt': 0,
    'status': {},
    'condition': {},
    'tickers': [],

    'max_hits': 100,
    'hits': 100,
    'max_stamina': 100,
    'stamina': 100,
    'max_mana': 0,
    'mana': 0,
    'max_focus': 100,
    'focus': 100,
    'max_adrenalin': 10,
    'adrenalin': 10,
    'max_fabric': 100,
    'fabric': 100,
    'regen_hits': 0,
    'regen_stamina': 0,
    'regen_mana': 0,
    'regen_focus': 0,
    'regen_adrenalin': 0,
    'regen_fabric': 0,
    'regen_mods': [0.0] * 8,
}

added = []
skipped = []

for name, default in props.items():
    if name in target.properties:
        skipped.append(name)
    else:
        target.add_property(name, default)
        added.append(name)

db.save_object(target)

if added:
    pobj.msg(f"Added to #{target.objnum}: {', '.join(added)}")
if skipped:
    pobj.msg(f"Already set: {', '.join(skipped)}")
if not added:
    pobj.msg("Nothing to do.")
