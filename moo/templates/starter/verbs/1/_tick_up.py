"""
_tick_up — generic regen-to-max ticker callback
Names: _tu_hits, _tu_stamina, _tu_mana, _tu_focus, _tu_adrenalin, _tu_fabric
Per-tick regen rate is stored in regen_<prop> by the _resource drain.

Aliases: _tu_hits, _tu_stamina, _tu_mana, _tu_focus, _tu_adrenalin, _tu_fabric
Hidden:  yes
"""

_TU = {
    '_tu_hits':      ('hits',      'max_hits',      'regen_hits'),
    '_tu_stamina':   ('stamina',   'max_stamina',   'regen_stamina'),
    '_tu_mana':      ('mana',      'max_mana',      'regen_mana'),
    '_tu_focus':     ('focus',     'max_focus',     'regen_focus'),
    '_tu_adrenalin': ('adrenalin', 'max_adrenalin', 'regen_adrenalin'),
    '_tu_fabric':    ('fabric',    'max_fabric',    'regen_fabric'),
}

def _w(o, p, v):
    try:
        o.set_property(p, v)
    except Exception:
        o.add_property(p, v)

cfg = _TU.get(verb)
if cfg:
    prop, max_prop, rate_prop = cfg
    idstring = f'{verb}_{this.objnum}'

    current = getattr(this, prop, 0) or 0
    ceiling = getattr(this, max_prop, 0) or 0
    rate = getattr(this, rate_prop, 1) or 1

    if ceiling <= 0:
        ticker_remove(this, idstring)
    elif current < ceiling:
        new_val = min(current + rate, ceiling)
        _w(this, prop, new_val)
        if new_val >= ceiling:
            ticker_remove(this, idstring)
    else:
        ticker_remove(this, idstring)
