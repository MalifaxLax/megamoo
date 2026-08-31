"""
Applies round time (action cooldown) to a character and starts the
tick-down timer to count it off. Round time prevents the character
from taking most actions until it expires.

Called: call_verb(pobj, '_rt', amount=3)  or  pobj._rt(3)

Arguments:
    amount - Seconds of round time to add (adjusted by rt_regen_mod).

Starts a 1-second ticker (_td_rt) that decrements rt by 1 each second
until it reaches zero.

Hidden:  yes
"""

try:
    seconds = amount
except NameError:
    seconds = int(args) if args else 0
mod = this.rt_regen_mod or 0
this.rt = (this.rt or 0) + seconds + mod
ticker_add(1, '_td_rt', this, f'_td_rt_{this.objnum}')
