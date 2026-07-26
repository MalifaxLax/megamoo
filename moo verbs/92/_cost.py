"""
_cost helper on #92 (BaseMerchant) -- hidden.

Return the asking price (int) this merchant quotes the buyer for <cqty>
of <citem>.  Called by the room buy verb:

    call_verb(merchant, '_cost', citem=<obj>, cqty=<int>)

Here `pobj` is the buyer and `this` is the merchant, so the price can
draw on both sides:

    value(item) * qty * race_mod * guild_mod * char_mod * trade_factor

Every factor is read defensively and defaults to a 1.0 no-op, so a bare
merchant with no mod tables still quotes a sane price.  The buyer's
personal standing (char_mod) is read here but only *persisted* at
purchase time (offer/accept) -- a player can't write merchant props.
"""

# Read kwargs into fresh locals (never reassign a call_verb kwarg name).
it = citem
q = cqty or 1

# Base value: the item itself, or the liquid it holds.
val = getattr(it, 'value', None)
if val is None:
    lt = getattr(it, 'ltype', None)
    val = getattr(lt, 'value', 0) if (lt and hasattr(lt, 'objnum')) else 0
val = val or 0

def _mod(table, key):
    if not table or key is None:
        return 1.0
    return table.get(key, 1.0) or 1.0

race_mod = _mod(getattr(this, 'race_mods', None), getattr(pobj, 'race', None))
guild_mod = _mod(getattr(this, 'guild_mods', None),
                 getattr(pobj, 'guild', None) or getattr(pobj, 'charclass', None))

char_mods = getattr(this, 'char_mods', None) or {}
char_mod = char_mods.get('mod_%d' % pobj.objnum, 1) or 1  # first-timer => 1.0

# Trading skill discounts the price, down to a floor.  Both knobs are
# overridable per merchant.
skill_bonus = getattr(pobj, 'skill_bonus', None) or {}
trading = skill_bonus.get('trading', 0) or 0
rate = getattr(this, 'trade_rate', 0.01) or 0.0
floor = getattr(this, 'trade_floor', 0.50) or 0.0
trade_factor = max(floor, 1.0 - trading * rate)

price = val * q * race_mod * guild_mod * char_mod * trade_factor
return max(1, int(round(price)))
