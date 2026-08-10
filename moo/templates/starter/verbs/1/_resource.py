"""
_resource verb on #1 (RootObject).

Generic resource drain shared by the per-resource call names:
    _hits, _stamina, _mana, _focus, _adrenalin, _fabric

Called: call_verb(pobj, '_hits', amount=10[, interval=60])

Drains <amount> from the resource, stores the per-tick regen rate in the
character's regen_<prop> slot, and starts the matching _tu_<prop> ticker to
recover it.  All property names match the @initchar character template:
    <prop>          current value   (hits, stamina, mana, focus, adrenalin, fabric)
    max_<prop>      ceiling
    regen_<prop>    per-tick regen rate (written here, read by _tick_up)
    regen_mods[idx] per-resource regen modifier (float; built by _recalc_combat)

regen_mods index order (see #5._recalc_combat):
    0 hits, 1 fabric, 2 stamina, 3 mana, 4 focus, 5 psy, 6 adrenalin, 7 bft

Aliases: _hits, _stamina, _mana, _focus, _adrenalin, _fabric
Hidden:  yes
"""

# Read the injected kwarg into a NEW name -- reassigning `amount` itself would
# make it verb-local, so `try: amount` would raise UnboundLocalError and clobber
# the kwarg to 0.  See [[verb-kwarg-idiom-gotcha]].
try:
    _amt = amount
except NameError:
    _amt = int(args) if args else 0

# verb -> (prop, max_prop, rate_prop, regen_mods index, tick_up_verb, default_interval)
_RES = {
    '_hits':      ('hits',      'max_hits',      'regen_hits',      0, '_tu_hits',      60),
    '_stamina':   ('stamina',   'max_stamina',   'regen_stamina',   2, '_tu_stamina',   10),
    '_mana':      ('mana',      'max_mana',      'regen_mana',      3, '_tu_mana',      10),
    '_focus':     ('focus',     'max_focus',     'regen_focus',     4, '_tu_focus',      3),
    '_adrenalin': ('adrenalin', 'max_adrenalin', 'regen_adrenalin', 6, '_tu_adrenalin', 12),
    '_fabric':    ('fabric',    'max_fabric',    'regen_fabric',    1, '_tu_fabric',     3),
}

def _w(o, p, v):
    # Ungated write: set_property (add_property if the prop is new) skips the
    # safe_setattr() permission gate, which would otherwise block this drain
    # from writing an 'rc'-perm prop on a character that doesn't own itself.
    try:
        o.set_property(p, v)
    except Exception:
        o.add_property(p, v)

cfg = _RES.get(verb)
if cfg:
    prop, max_prop, rate_prop, mod_idx, tu_verb, default_interval = cfg

    # Drain the resource
    current = max(0, (getattr(this, prop, 0) or 0) - _amt)
    _w(this, prop, current)

    # Per-tick regen rate -> regen_<prop>; modifier from regen_mods[idx]
    rmods = this.regen_mods or []
    mod = (rmods[mod_idx] if mod_idx < len(rmods) else 0) or 0
    if prop == 'hits':
        rate = max(1, current // 10) + mod
    else:
        rate = max(1, 1 + mod)
    _w(this, rate_prop, int(rate))

    # Defensive: ensure the ceiling exists (the @initchar template provides it)
    if not getattr(this, max_prop, None):
        _w(this, max_prop, 100)

    # Start regen ticker (provided interval or per-resource default)
    try:
        tick_interval = interval
    except NameError:
        tick_interval = default_interval
    idstring = f'{tu_verb}_{this.objnum}'
    ticker_add(tick_interval, tu_verb, this, idstring)
