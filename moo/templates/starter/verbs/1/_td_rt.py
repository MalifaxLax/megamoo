"""
_td_rt — count roundtime down to zero

Roundtime only. This used to be a generic decrement-to-zero ticker that
also ran the thirteen afflictions, each on its own ticker keyed by verb
name -- which meant a table of names that had to stay in step with the
verb's own alias list, and did not: they were declared on a `Names:`
line, which the engine does not read, so twelve of the fourteen fired at
nothing.

The afflictions live on $eu now, where the effect name is the handler's
own name and there is no table to drift from. Roundtime stays here
because it is not an affliction: `do_wait` reads `rt` on every command a
character types, and it is a bare number rather than an entry in a dict
that other code renders.

Called by ticker_add() — no args.

Aliases: _tick_down
Hidden:  yes
"""

# Write via DIRECT attribute assignment.  Direct assignment uses the lenient
# update path; setattr(this, 'rt', val) would route through the strict
# can_write permission gate and fail, because rt carries 'rc' perms (no write
# bit) and a character does not own itself.  The ticker fires in the
# character's (non-wizard) context, so setattr() floods "cannot write 'rt'"
# and the timer never ticks.
val = getattr(this, 'rt', 0) or 0
val = int(round_from_nine(max(0, val - 1)))
this.rt = val
if val <= 0:
    ticker_remove(this, f'{verb}_{this.objnum}')
