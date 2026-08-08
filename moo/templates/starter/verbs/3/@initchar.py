"""
Sets all missing ICharacter properties (hand, mh, oh, load, wearing,
desclist, rt, position) on an existing character. Use this to
retroactively initialize characters created before chargen added
these properties.

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
    'wearing': [],
    'desclist': ['', '', '', ''],
    'rt': 0,
    'position': 0,
    'race': None,
    'charclass': None,
    'gender': None,
    'last_name': None,
    'chargen_step': None,
    'cstats': [0] * 10,
    'mstats': [0] * 10,
    'racial_stat_mods': [0] * 10,
    'class_stat_mods': [0] * 10,
    'classprimereqs': [],
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
    'level': 1,
    'experience': 0,
    'fitness': 0,
    'body_training': 0,
    'builds_per_lvl': 0,
    'craft_builds_per_lvl': 0,
    'builds_available': 0,
    'craft_builds_available': 0,
    'exp_per_lvl': 0,
    'exp_per_build': 0,
    'exp_per_craft_build': 0,
    'static_exp_per_lvl_mod': 0,
    'build_mod': 0,
    'craft_build_mod': 0,
    'craft_aptitude': 0,
    'skill_rank': {},
    'skill_mod': {},
    'skill_bonus': {},
    'skill_cost': {},
    'ranks_trained_this_lvl': {},
    'skill_ranks_trainable_per_lvl': {},
    'trainings_available': {},
    'trainings_available_per_cost': {},
    'multi_train_completions': {},
    'multi_train_lvl': {},
    'magic_realm': None,
    'magic_stats': [],
    'appearancedic': {},
    'rr_essence': 0,
    'rr_channeling': 0,
    'rr_mentalism': 0,
    'rr_disease': 0,
    'rr_poison': 0,
    'regen_rt': 0,
    'regen_stamina': 0,
    'regen_mana': 0,
    'regen_focus': 0,
    'regen_adrenalin': 0,
    'regen_fabric': 0,
    'regen_hits': 0,
    'prelogout_location': None,
    # --- Commerce state (read/written by the buy/offer system) ---
    'pending_buy': None,
    # --- Combat state (read/written by the combat system) ---
    'status': {},
    'condition': {},
    'wear_list': [[] for _ in range(47)],
    # Cached per-position combat arrays (rebuilt by _recalc_combat on wear/remove)
    'body_at': [[] for _ in range(47)],
    'body_db_mods': [[0] * 5 for _ in range(47)],
    'body_crit_mods': [[0] * 9 for _ in range(47)],
    'body_dam_mods': [[0.0] * 9 for _ in range(47)],
    # Whole-body cumulative combat mods
    'omods': [0, 0],
    'dmods': [0, 0],
    'full_body_dmods': [0, 0],
    'crit_res': [0] * 9,
    'dam_res': [100] * 9,
    'regen_mods': [0.0] * 8,
    'stat_mods': [0] * 10,
    'maneuver_mod': 0,
    # Combat bookkeeping written during fights
    'tickers': [],
    'wounds': [],
    'combat_bonus': 0,
    'combat_penalty': 0,
    'body_damage': {},
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
