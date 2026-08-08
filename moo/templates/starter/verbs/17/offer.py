"""
offer verb on #17 (ICRoom).

Close (or attempt) the purchase quoted by a prior `buy`.  `buy` stashes
the deal on pobj.pending_buy (merchant, item, npc, ...); `offer` reads it
back, validates the coin and amount, takes payment, and hands over a
freshly-minted copy of the goods.

Usage:
    offer                          pay the quoted price outright
    offer <amount> <coin>          e.g.  offer 57 plats

Pipeline (abort with a spoken refusal at the first failing gate).  A bare
`offer` skips the coin gate and offers exactly the computed cost in the
merchant's own coin; the explicit form haggles a stated amount:
    1. coin  -- the offered coin must be the one this merchant deals in;
       merchant.coin_type indexes merchant.ctypes.  The buyer's coin word
       need only *start with* a ctypes entry ("plats" -> "plat").  Wrong
       coin -> npc 'coin_fail' (&1 = the coin we DO take, a string).
    2. price -- cost = item.value * pending vmult * exchange[coin_type]
       * pending qty (vmult is the vessel price multiplier for
       poured-to-order liquids, 1 otherwise; qty is 12 for a case, 6
       for a half-case, else 1).  offered < cost -> npc 'offer_fail'
       (&D = item via dob, &1 = cost phrase string).
    3. funds -- the buyer must actually hold what they offered;
       cash[coin_type] < offered -> npc 'cash_fail'.
    4. hands -- a free hand is needed (both for a two-handed item).
       Bulk buys arrive boxed, so one free hand always suffices there.
    5. settle -- mint the goods, place them in hand, subtract *cost*
       (not the offer) from cash, speak 'sell' to the buyer and
       'o_sell' to the room.  For a plain stock item the mint clones
       the stock prototype; for a poured-to-order liquid (pending_buy
       vproto set by buy) it clones the VESSEL prototype, pours the
       liquid into it (ltype + cuses = vessel capacity), prices it at
       the per-unit charge, and normalizes its vessel-only name via
       #28:_ctitle -- a cup is titled "a shot glass", never "a shot
       glass of fire whiskey"; the liquid shows on look, not in the
       name.  A case / half-case mints qty units of either kind into a
       fresh box (child of #26 BaseContainer) sized to hold them, and
       the BOX -- titled bare, "a case" / "a half-case" -- is what
       goes into the buyer's hand.

Messages: objects render through esub dob/iob (&d/&D, &i/&I); raw strings
(coin name, cost phrase) render through &N.
    coin_fail  -> &1 = the accepted coin (string)
    offer_fail -> &D  = the item (dob), &1 = cost phrase (string)
    sell       -> &d  = the goods (dob), spoken to the buyer
    o_sell     -> &d  = the buyer (dob), &i = the goods (iob), to the room
Fall back to the merchant/#92 default for the *_fail trio.
sell/o_sell render the minted goods by their OWN name -- the serve line
says "serves you a shot glass"; the full order description ("a shot
glass of fire whiskey") belongs to the buy quote, not the handover.

Plurals: any coin word printed alongside a cost gets an 's' when cost > 1.
"""

pb = pobj.pending_buy or {}
m_num, it_num = pb.get('merchant'), pb.get('item')
if not m_num or not it_num:
    pobj.msg("You haven't haggled for anything yet.  Try 'buy <item>' first.")
    return

merchant = db.get_object(m_num)
item = db.get_object(it_num)
if not merchant or not item or item.existent != True:
    pobj.msg("That deal's gone stale.  Try 'buy <item>' again.")
    pobj.pending_buy = {}
    return

# The merchant must still be the one serving this room.
room_m = pobj.location.merchant
if not room_m or room_m.objnum != merchant.objnum:
    pobj.msg("There's no one here to take that offer.")
    return

npcs = merchant.npcs or {}
npc = npcs.get(pb.get('npc')) or next(iter(npcs.values()), None)

def _say(text, **subkw):
    """Speak a line as the npc.  Any s0=/s1=/... kwargs are raw-string
    slots that esub splices into &0/&1/... in `text`."""
    if not text:
        return
    sp = (npc and npc.get('name')) or merchant.speaker \
        or merchant.name
    pobj.msg(sp[:1].upper() + sp[1:] + ' says, "' + text + '"', **subkw)

def _field(key):
    """npc override first, then the merchant/#92 default."""
    v = npc.get(key) if npc else None
    return v if v else getattr(merchant, key, None)

# ── Parse "offer [<amount> <coin>]" ──────────────────────────────────
# Bare `offer` accepts the deal at the asking price; the two-arg form
# haggles an explicit amount in an explicit coin.
raw = dobj if isinstance(dobj, str) else ''
if not raw:
    raw = ' '.join(args) if isinstance(args, (list, tuple)) else (args or '')
parts = str(raw).split()
offered = None      # None -> bare offer: pay the computed cost outright
in_coin = None
if parts:
    if len(parts) < 2:
        pobj.msg("Offer how much of what?  (offer <amount> <coin>, "
                 "or just 'offer' to pay the asking price)")
        return
    try:
        offered = int(parts[0])
    except (ValueError, TypeError):
        pobj.msg("Offer a number, like 'offer 57 plats'.")
        return
    in_coin = ' '.join(parts[1:]).strip().lower()

# ── 1. Coin check (explicit offers only; bare pays the house coin) ───
ctypes = merchant.ctypes or []
coin_idx = merchant.coin_type or 0
exchange = merchant.exchange or []
accepted = ctypes[coin_idx] if coin_idx < len(ctypes) \
    else (ctypes[0] if ctypes else 'coin')

if in_coin is not None:
    matched = None
    for i, ct in enumerate(ctypes):
        if ct and in_coin.startswith(str(ct).lower()):
            matched = i
            break
    if matched is None or matched != coin_idx:
        _say(_field('coin_fail'), s1=accepted)
        return

# ── 2. Price check ───────────────────────────────────────────────────
# The quote was for qty units (case = 12, half-case = 6), so the charge
# is qty x the unit price.  unit_cost is kept separately to price each
# minted unit at settlement.
rate = exchange[coin_idx] if coin_idx < len(exchange) else 1
vmult = pb.get('vmult') or 1
qty = pb.get('qty') or 1
qty_type = pb.get('qty_type') or 'single'
unit_cost = max(1, int(round(item.value * vmult * rate)))
cost = max(1, int(round(item.value * vmult * rate * qty)))
coin_disp = accepted + ('s' if cost != 1 else '')

if offered is None:
    offered = cost
if offered < cost:
    _say(_field('offer_fail'), dob=item, s1="%d %s" % (cost, coin_disp))
    return

# ── 3. Funds check (must hold at least what was offered) ─────────────
cash = list(pobj.cash or [])
have = cash[coin_idx] if coin_idx < len(cash) else 0
if have < offered:
    _say(_field('cash_fail') or "Ye don't have that kind o' coin.")
    return

# ── 4. Hands check ───────────────────────────────────────────────────
# A bulk buy is handed over as one box, so it only ever needs one hand.
free = call_verb(pobj, 'hands_free')
need = 1 if qty > 1 else ((item.hands or 1))
if not free or (need == 2 and free != 'both'):
    pobj.msg("Your hands are too full.")
    return

# ── 5. Settle: mint the goods, take payment, narrate ─────────────────
# Clone into a standalone item (the zone-spawner idiom): same parent,
# copy every own property, then native noun/aliases.  Owned by the
# buyer so this player-context verb may write its natives.  The clone
# SOURCE is the vessel prototype for a poured-to-order liquid, the
# stock item itself otherwise.  NB set_property only lands for props
# DEFINED somewhere on the clone's parent chain; others skip silently.
vproto = db.get_object(pb['vproto']) if pb.get('vproto') else None
if vproto is not None and not hasattr(vproto, 'objnum'):
    vproto = None
src = vproto if vproto is not None else item

def _mint():
    g = create(src.parent, pobj.objnum)
    for _pname, _pinfo in (src.properties or {}).items():
        _val = _pinfo.get('value') if isinstance(_pinfo, dict) \
            else getattr(_pinfo, 'value', _pinfo)
        try:
            g.set_property(_pname, _val)
        except Exception:
            pass
    # noun/aliases are native instance attributes (not MOO properties).
    try:
        g.noun = src.noun
        g.aliases = list(src.aliases) if src.aliases else []
    except Exception:
        pass
    if vproto is not None:
        # Pour: fill the fresh vessel with the ordered liquid, price it
        # at the per-unit charge, and regenerate the name from structure.
        g.ltype = item
        g.cuses = (vproto.uses or 1)
        g.set_property('value', unit_cost)
        call_verb(g, '_ctitle')
    return g

if qty == 1:
    goods = _mint()
else:
    # Bulk: mint qty units into a fresh box so the buyer carries (and
    # the hands check gated) ONE object.  The box is a direct child of
    # #26 BaseContainer; #26's stock caps (max_items_in 10) are too
    # small for a case, so size it to its cargo.  Like a cup, its title
    # is the bare container -- "a case" -- never the contents; what's
    # inside shows on `look in case`.
    goods = create(26, pobj.objnum)
    try:
        goods.noun = 'half-case' if qty_type == 'halfcase' else 'case'
        goods.aliases = ['case', 'box'] \
            + (['half-case'] if qty_type == 'halfcase' else [])
    except Exception:
        pass
    goods.name_mod_list = ['a', '', '', '', '']
    call_verb(goods, '_title')
    _in, _wsum, _vsum = [], 0, 0
    for _n in range(qty):
        _u = _mint()
        move(_u, goods)
        _in.append(_u.objnum)
        _wsum += _u.weight or 0
        _vsum += getattr(_u, 'volume', None) or 0
    goods.in_contents = _in
    goods.current_weight_in = _wsum
    goods.current_vol = _vsum
    goods.set_property('max_items_in',
                       max(qty, goods.max_items_in or 0))
    goods.set_property('max_weight_in',
                       max(_wsum, goods.max_weight_in or 0))
    goods.set_property('max_vol',
                       max(_vsum, goods.max_vol or 0))
    goods.set_property('value', cost)
    # The box's own weight carries its cargo, so load tracking below
    # charges the buyer for the whole case (+1 for the box itself).
    goods.set_property('weight', _wsum + 1)

move(goods, pobj)
call_verb(pobj, 'move_to_hand', dobj=goods)
pobj.load = (pobj.load or 0) + (goods.weight or 0)

while len(cash) <= coin_idx:
    cash.append(0)
cash[coin_idx] = have - cost
pobj.cash = cash

# sell (to the buyer) and o_sell (to the room).  Objects go through
# dob/iob (%d/%i): sell -> the goods; o_sell -> the buyer (%d) + goods (%i).
# The goods render by their OWN name ("serves you a shot glass") -- the
# full order description was the quote's job, not the handover's.
sell = _field('sell')
o_sell = _field('o_sell')
if sell:
    pobj.msg(sell, dob=goods)
if o_sell and not pobj.invis:
    pobj.location.msg_room(o_sell, exclude=[pobj], dob=pobj, iob=goods)

pobj.pending_buy = {}
