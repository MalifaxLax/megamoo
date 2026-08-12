"""
_tick_down — generic decrement-to-zero ticker callback

Called by ticker_add() — no args, uses `verb` to identify which timer,
which is why every timer name has to be a name of *this* verb. The list
below is the _TD table's keys; they must stay in step, because a name in
_TD that is not an alias is a ticker that fires at nothing. That was the
state until now: the names were declared on a `Names:` line, which the
engine does not read -- it parses Aliases, Abbrev, Hidden and Perms and
nothing else -- so only _td_rt and _tick_down existed, and the thirteen
afflictions _afflict starts would have applied and then never expired.

Aliases: _td_unconscious, _td_sleeping, _td_stunned, _td_paralyzed, _td_intoxicated, _td_immobilized, _td_entangled, _td_imprisoned, _td_webbed, _td_bound, _td_no_parry, _td_must_parry, _td_blind, _tick_down
Hidden:  yes
"""

# Config: verb_name -> (property, dict_key_or_None, step)
_TD = {
    '_td_rt':           ('rt', None, 1),
    '_td_unconscious':  ('status', 'unconscious', 1),
    '_td_sleeping':     ('status', 'sleeping', 1),
    '_td_stunned':      ('status', 'stunned', 1),
    '_td_paralyzed':    ('status', 'paralyzed', 1),
    '_td_intoxicated':  ('status', 'intoxicated', 1),
    '_td_immobilized':  ('condition', 'immobilized', 1),
    '_td_entangled':    ('condition', 'entangled', 1),
    '_td_imprisoned':   ('condition', 'imprisoned', 1),
    '_td_webbed':       ('condition', 'webbed', 1),
    '_td_bound':        ('condition', 'bound', 1),
    '_td_no_parry':     ('status', 'no_parry', 1),
    '_td_must_parry':   ('status', 'must_parry', 1),
    '_td_blind':        ('status', 'blind', 1),
}

# Write a countdown property via DIRECT attribute assignment.  Direct
# assignment uses the lenient update path; setattr(this, prop, val) would
# route through the strict can_write permission gate and fail, because these
# props (rt/status/condition) carry 'rc' perms (no write bit) and a character
# does not own itself.  The ticker fires in the character's (non-wizard)
# context, so setattr() floods "cannot write 'rt'" and the timer never ticks.
def _write(obj, prop, value):
    if prop == 'rt':
        obj.rt = value
    elif prop == 'status':
        obj.status = value
    elif prop == 'condition':
        obj.condition = value
    else:
        setattr(obj, prop, value)

cfg = _TD.get(verb)
if cfg:
    prop, key, step = cfg
    idstring = f'{verb}_{this.objnum}'

    if key is None:
        # Simple property (e.g. rt)
        val = getattr(this, prop, 0) or 0
        val = int(round_from_nine(max(0, val - step)))
        _write(this, prop, val)
        if val <= 0:
            ticker_remove(this, idstring)
    else:
        # Dict property (e.g. status['stunned'])
        d = getattr(this, prop, None)
        if d and key in d and d[key] > 0:
            d[key] = int(round_from_nine(max(0, d[key] - step)))
            _write(this, prop, d)  # reassign to trigger save
            if d[key] <= 0:
                ticker_remove(this, idstring)
        else:
            ticker_remove(this, idstring)
