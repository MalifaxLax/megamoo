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

# Every property here is read by a verb this world ships.  It used to
# carry a whole RPG on top -- stats, skills, resistances, training and
# crafting budgets, per-body-part combat arrays: 59 properties that no
# shipped verb touched, seeded onto every character in every world built
# from this template.  A starter world should not decide what genre you
# are writing.  Add your own here; that is what this table is for.
props = {
    # Hands and carrying
    'hand': ['right', 'left'],
    'mh': None,
    'oh': None,
    'load': 0,

    # Who they are -- filled in by chargen
    'desclist': ['', '', '', ''],
    'gender': None,
    'last_name': None,
    'chargen_step': None,
    'level': 1,

    # Posture, roundtime and the conditions that gate acting
    'position': 0,
    'rt': 0,
    'status': {},
    'condition': {},
    'tickers': [],

    # Resource pools.  Drained by _resource on #1 and recovered by the
    # matching _tu_* ticker in _tick_up; regen_<pool> is the per-tick
    # rate those two write and read, and regen_mods holds the per-pool
    # modifier, indexed 0 hits, 1 fabric, 2 stamina, 3 mana, 4 focus,
    # 5 psy, 6 adrenalin, 7 bft.
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
