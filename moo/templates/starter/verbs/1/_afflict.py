"""
_afflict — apply a status/condition effect and start tick-down
Names: _immobilize, _entangle, _imprison, _web, _bind,
_unconscious, _sleep, _stun, _paralyze, _intoxicate,
_no_parry, _must_parry, _blind
Called: call_verb(pobj, '_stun', duration=5)  OR  pobj._stun(5)
Kwarg: duration (int) — seconds of effect (stacks with existing)

Aliases: _immobilize, _entangle, _imprison, _web, _bind, _unconscious, _sleep, _stun, _paralyze, _intoxicate, _no_parry, _must_parry, _blind
Hidden:  yes
"""

# Read the injected kwarg into a NEW name -- reassigning `duration` itself would
# make it verb-local, so `try: duration` would raise UnboundLocalError and clobber
# the kwarg to 0.  See [[verb-kwarg-idiom-gotcha]].
try:
    _dur = duration
except NameError:
    _dur = int(args) if args else 0

# Config: verb_name -> (dict_property, dict_key, tick_down_verb)
_AFF = {
    '_immobilize':  ('condition', 'immobilized', '_td_immobilized'),
    '_entangle':    ('condition', 'entangled', '_td_entangled'),
    '_imprison':    ('condition', 'imprisoned', '_td_imprisoned'),
    '_web':         ('condition', 'webbed', '_td_webbed'),
    '_bind':        ('condition', 'bound', '_td_bound'),
    '_unconscious': ('status', 'unconscious', '_td_unconscious'),
    '_sleep':       ('status', 'sleeping', '_td_sleeping'),
    '_stun':        ('status', 'stunned', '_td_stunned'),
    '_paralyze':    ('status', 'paralyzed', '_td_paralyzed'),
    '_intoxicate':  ('status', 'intoxicated', '_td_intoxicated'),
    '_no_parry':    ('status', 'no_parry', '_td_no_parry'),
    '_must_parry':  ('status', 'must_parry', '_td_must_parry'),
    '_blind':       ('status', 'blind', '_td_blind'),
}

def _w(o, p, v):
    # Ungated write: set_property (add_property if the prop is new) skips the
    # safe_setattr() permission gate, which would otherwise block one character
    # from writing a status/condition dict on another it doesn't own.
    try:
        o.set_property(p, v)
    except Exception:
        o.add_property(p, v)

cfg = _AFF.get(verb)
if cfg:
    dict_prop, key, td_verb = cfg

    # Read dict, add duration (stacking), reassign to trigger save
    d = getattr(this, dict_prop, None)
    if d is not None and key in d:
        d[key] = (d[key] or 0) + _dur
        _w(this, dict_prop, d)

        # Start tick-down (idempotent — ticker_add with same idstring replaces)
        idstring = f'{td_verb}_{this.objnum}'
        ticker_add(1, td_verb, this, idstring)
