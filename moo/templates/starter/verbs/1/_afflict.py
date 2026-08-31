"""
_afflict — apply a status or condition effect for a while

Hands the affliction to the effects system and stops there. $eu owns the
schedule, the countdown, the expiry and cancelling; the do_<effect> verb
on #33 owns the status/condition dict. This maps the name a caller types
to the name $eu knows it by, and nothing else.

(There is no `Names:` line here any more. It read like a declaration and
was prose -- the engine parses Aliases, Abbrev, Hidden and Perms, and
nothing else -- and the identical line on #1:_td_rt left thirteen timers
declared nowhere at all.)

Called: call_verb(pobj, '_stun', duration=5)  OR  pobj._stun(5)
Kwarg: duration (int) — seconds of effect (stacks with existing)

Aliases: _immobilize, _entangle, _imprison, _web, _bind, _unconscious, _sleep, _stun, _paralyze, _intoxicate, _no_parry, _must_parry, _blind
Hidden:  yes
"""

try:
    _dur = duration
except NameError:
    _dur = int(args) if args else 0

_AFF = {
    '_immobilize':  'immobilize',
    '_entangle':    'entangle',
    '_imprison':    'imprison',
    '_web':         'web',
    '_bind':        'bind',
    '_unconscious': 'unconscious',
    '_sleep':       'sleep',
    '_stun':        'stun',
    '_paralyze':    'paralyze',
    '_intoxicate':  'intoxicate',
    '_no_parry':    'no_parry',
    '_must_parry':  'must_parry',
    '_blind':       'blind',
}

effect = _AFF.get(verb)
if effect and _dur > 0:
    _effects.trigger(this, effect, int(_dur), 1)
