"""
buy verb on #17 (ICRoom).

Ask the room's merchant for a price on something.  This verb only QUOTES
a price -- no goods or coin change hands here.  The buyer commits with the
`offer` verb, which reads the pending quote this verb stashes on
pobj.pending_buy.

Usage:
    buy <item>                    - buy whiskey
    buy <container> of <liquid>   - buy a glass of fire whiskey
    buy <vessel> of <liquid>      - buy a bottle of fire whiskey (poured
                                    to order, priced per vessel)
    buy case of <item>            - 12 of the item
    buy half a case of <item>     - 6 of the item, boxed

Liquid containers are structured objects: the vessel is noun +
name_mod_list (noun 'glass', adjective 'shot'), and its TITLE is the
vessel alone -- "a shot glass" full or empty (#28:_ctitle; the liquid
shows on look, never in the name).  Matching a filled stock cup
therefore goes through its ltype: when the flat match misses, "buy
glass of fire whiskey" splits on " of " and matches the vessel and
the liquid separately (so "buy glass of ale" correctly fails against
a glass of whiskey), and a bare "buy whiskey" is checked against the
liquid each stocked cup holds.  We only pre-parse the "case of" /
"half a case of" quantity words ("of" is not a parser preposition, so
the whole phrase arrives as `dobj`).

POURED TO ORDER (the legacy #199:_myMatch mods capability, rebuilt):
a merchant may stock a bare LIQUID (#91 BaseDrinkable descendant) and
carry `merchant.vessels`, a list of {'proto': <empty-cup objnum>,
'mult': <price multiplier>} options, first entry = the default.  Then
"buy whiskey" quotes the liquid in the default vessel, and "buy bottle
of fire whiskey" quotes it in the bottle at liquid price x mult.  buy
stashes the chosen vessel in pending_buy (vproto/vmult); `offer` mints
the vessel, pours the liquid (ltype + cuses), and retitles it via
#28:_ctitle.

Messages: npc speech renders via esub.  Objects go through dob/iob
(%d/%D, %i/%I); raw strings (price, currency) go through %N.  cost_emit:
%d = the goods (dob), %1 = asking price, %2 = currency.  The currency word
is derived from the merchant's coin model (ctypes[coin_type]), pluralized
for the quoted price -- there is no separate merchant.currency property.
The quote line ends with a how-to-buy prompt OUTSIDE the quotation marks,
same line ("... Ye want one?" If you would like to purchase <desc> make an
'offer'.) -- overridable via npc/merchant cost_help ('' suppresses it).
"""

import re

if call_verb(pobj, 'do_wait'):
    return

merchant = getattr(pobj.location, 'merchant', None)
if not merchant or not hasattr(merchant, 'objnum'):
    pobj.msg("There is no one to buy from here.")
    return

# ── Pick the shopkeeper (npc) speaking for this merchant ─────────────
# merchant.npcs is a dict of {npc_key: {'name', 'cost_emit', 'sell', ...}}.
# The merchant object is a back-end price book, never an in-room NPC --
# the npc's 'name' is what the player hears, not merchant.name.  With a
# single shop we just take the configured npc (active_npc, else first).
npcs = getattr(merchant, 'npcs', None) or {}
npc_key = getattr(merchant, 'active_npc', None)
if npc_key and npc_key in npcs:
    npc = npcs[npc_key]
elif npcs:
    npc_key, npc = next(iter(npcs.items()))
else:
    npc, npc_key = None, None

if not dobj:
    pobj.msg("Buy what?")
    return

def _say(text, suffix='', **subkw):
    """Speak a line as the npc.  Any s0=/s1=/... kwargs are raw-string
    slots that esub splices into %0/%1/... in `text`.  `suffix` is
    unspoken narration appended to the same line, after the closing
    quote mark."""
    sp = (npc and npc.get('name')) or getattr(merchant, 'speaker', None) \
        or merchant.name
    line = sp[:1].upper() + sp[1:] + ' says, "' + text + '"'
    if suffix:
        line += ' ' + suffix
    pobj.msg(line, **subkw)

def _core(it):
    """The 'fire whiskey' part of a name for case descriptions.  For a
    filled cup that's the liquid's own name (a case of the drink, not
    of the vessels); otherwise the item's adjectives + noun from
    name_mod_list [article, adj1, adj2, adj3, trailer], dropping the
    article and trailer."""
    lt = getattr(it, 'ltype', None)
    if lt is not None and hasattr(lt, 'objnum'):
        return lt.name
    nml = getattr(it, 'name_mod_list', None) or []
    adjs = [a.strip() for a in nml[1:4] if a and a.strip()]
    noun = (getattr(it, 'noun', None) or it.name).strip()
    return ' '.join(adjs + [noun]) if adjs else noun

# ── Peel off the case / half-case quantity words ─────────────────────
req = dobj.strip()
qty_type, qty = 'single', 1
m = re.match(r'^(?:a |an |the )?half(?: a)?[ -]case of (.+)$', req, re.I)
if m:
    qty_type, qty, req = 'halfcase', 6, m.group(1).strip()
else:
    m = re.match(r'^(?:a |an |the )?case of (.+)$', req, re.I)
    if m:
        qty_type, qty, req = 'case', 12, m.group(1).strip()

# ── Compile stock and match it the ordinary way ──────────────────────
# merchant.items is an optional list of stock holders.  Its elements may be
# live objects, bare objnums, or "#N" strings depending on how it was set
# (verb assignment vs @set / MCP), so resolve each to an object first.
stock = getattr(merchant, 'items', None) or [merchant]
item_list = []
for holder in stock:
    if isinstance(holder, int) or (isinstance(holder, str)
                                   and holder[:1] == '#' and holder[1:].isdigit()):
        try:
            holder = db.get_object(int(str(holder).lstrip('#')))
        except Exception:
            holder = None
    if holder is not None and hasattr(holder, 'objnum'):
        for o in (getattr(holder, 'contents', None) or []):
            if o is not None and hasattr(o, 'objnum') and getattr(o, 'existent', True):
                item_list.append(o)

# ── Vessel options: liquids poured to order ──────────────────────────
# A liquid sitting in stock is an order base, not a hand-over item; the
# merchant's `vessels` list says what it can be served in and at what
# multiple of the liquid's price.  `parent` is stored as a raw objnum,
# so the ancestry walk resolves each link before comparing.
def _is_liquid(o):
    p = getattr(o, 'parent', None)
    for _ in range(20):
        if p is None or p == 0:
            return False
        if not hasattr(p, 'objnum'):
            try:
                p = db.get_object(int(str(p).lstrip('#')))
            except Exception:
                return False
            if p is None:
                return False
        if p.objnum == 91:
            return True
        p = getattr(p, 'parent', None)
    return False

vconfigs = []
for v in (getattr(merchant, 'vessels', None) or []):
    pn = v.get('proto') if isinstance(v, dict) else None
    if pn is None:
        continue
    try:
        proto = db.get_object(int(str(pn).lstrip('#')))
    except Exception:
        proto = None
    if proto is not None and hasattr(proto, 'objnum'):
        vconfigs.append((proto, v.get('mult', 1) or 1))

item = pmatch(req, pobj, item_list)
vessel = None  # (proto, mult) when the goods are a liquid poured to order

# ── "buy <container> of <liquid>" -- match vessel and liquid apart ────
# The flat match above already handles the canonical word order (it all
# appears in the generated name).  This fallback checks the two halves
# against the right objects -- the vessel against the cup, the liquid
# against its ltype -- so reversed or partial phrasings still land on
# the right stock item and wrong pairings stay unmatched.
if item is None and re.search(r'\s+of\s+', req, re.I):
    cpart, lpart = re.split(r'\s+of\s+', req, maxsplit=1, flags=re.I)
    for cand in item_list:
        lt = getattr(cand, 'ltype', None)
        if lt is None or not hasattr(lt, 'objnum'):
            continue
        if pmatch(cpart, pobj, [cand]) and pmatch(lpart, pobj, [lt]):
            item = cand
            break

# ── "buy <liquid>" against filled-cup stock ──────────────────────────
# A cup's title is the bare vessel ("a shot glass"), so the liquid's
# name never matches the cup itself -- check the ltype directly, and
# "buy whiskey" still finds a stocked glass of fire whiskey.
if item is None:
    for cand in item_list:
        lt = getattr(cand, 'ltype', None)
        if lt is not None and hasattr(lt, 'objnum') \
                and pmatch(req, pobj, [lt]):
            item = cand
            break

# ── "buy <vessel> of <liquid>" -- pour a stocked liquid to order ─────
if item is None and vconfigs and re.search(r'\s+of\s+', req, re.I):
    vpart, lpart = re.split(r'\s+of\s+', req, maxsplit=1, flags=re.I)
    lq = pmatch(lpart, pobj, [o for o in item_list if _is_liquid(o)])
    vp = pmatch(vpart, pobj, [p for p, _m in vconfigs])
    if lq is not None and vp is not None:
        item = lq
        vessel = next((p, m) for p, m in vconfigs if p.objnum == vp.objnum)

if item is None:
    _say("I don't have any of that.")
    return

# A bare liquid ("buy whiskey") gets the default (first) vessel.
if vessel is None and _is_liquid(item):
    if not vconfigs:
        _say("I've got nothing to serve that in.")
        return
    vessel = vconfigs[0]

# ── Merchant decides whether it'll sell this, and for how much ───────
reason = call_verb(merchant, '_merch_ok', citem=item, cqtype=qty_type)
if reason:
    _say(reason)
    return

asking = call_verb(merchant, '_cost', citem=item, cqty=qty)
if vessel is not None:
    asking = max(1, int(round(asking * vessel[1])))

# ── Describe the goods ───────────────────────────────────────────────
# A cup's title is the bare vessel, so a filled cup (or a poured order)
# is described by composing vessel + liquid: "a shot glass of fire
# whiskey" -- the quote says what's in it even though the name doesn't.
if qty_type == 'single':
    if vessel:
        desc = vessel[0].name + ' of ' + item.name
    else:
        lt = getattr(item, 'ltype', None)
        desc = (item.name + ' of ' + lt.name) \
            if (lt is not None and hasattr(lt, 'objnum')) else item.name
elif qty_type == 'case':
    desc = "a case of " + _core(item)
else:
    desc = "a half-case of " + _core(item)

# ── Work out the coin word to quote in ───────────────────────────────
# The coin name is the merchant's own: coin_type indexes ctypes.  Names
# are stored singular ('plat') so that offer's startswith() coin match
# works on what the player types ('plats'); we append the 's' for display
# here, plural unless the price is exactly 1 ("57 plats", "1 plat").
ctypes = getattr(merchant, 'ctypes', None) or []
coin_idx = getattr(merchant, 'coin_type', 0) or 0
coin = ctypes[coin_idx] if coin_idx < len(ctypes) \
    else (ctypes[0] if ctypes else 'coin')
currency = coin + ('s' if asking != 1 else '')

# ── Stash the pending quote for the `offer` verb, then speak it ──────
# cost_emit substitutes the goods as an object (dob -> %d/%D) and the price
# and currency as raw strings (%1 = asking, %2 = currency).  `offer`
# renders sell/o_sell itself, so nothing pre-rendered needs stashing here.
cost_emit = (npc and npc.get('cost_emit')) \
    or getattr(merchant, 'buy_quote', None) \
    or 'Lessee eer, %d costs %1 %2. Ye want one?'

pobj.pending_buy = {
    'merchant': merchant.objnum,
    'npc': npc_key,
    'item': item.objnum,
    'qty_type': qty_type,
    'qty': qty,
    'asking': asking,
    'currency': currency,
    'desc': desc,
    'vproto': vessel[0].objnum if vessel else None,
    'vmult': vessel[1] if vessel else None,
}

emit = cost_emit
if desc != item.name:
    # No single object carries the composed description (a case, a
    # poured order, or a filled cup whose title omits the liquid), so
    # splice the desc string over the goods tokens before esub runs
    # ("a shot glass of fire whiskey costs...", not "a shot glass").
    emit = re.sub(r'[%$]D', desc[:1].upper() + desc[1:], emit)
    emit = re.sub(r'[%$]d', desc, emit)

# ── The how-to-buy instruction ───────────────────────────────────────
# House prompt, not shopkeeper speech: appended to the quote line after
# the closing quote mark, unquoted.  Overridable per npc/merchant via
# cost_help ('' suppresses it); %d/%D render the composed description.
if npc and 'cost_help' in npc:
    help_line = npc.get('cost_help')
else:
    help_line = merchant.cost_help
    # == None, NOT `is None`: a missing MOO property reads as _null_attr,
    # which equals None but isn't it.  An explicit '' still suppresses.
    if help_line == None:  # noqa: E711
        help_line = "If you would like to purchase %d make an 'offer'."
if help_line:
    help_line = re.sub(r'[%$]D', desc[:1].upper() + desc[1:], help_line)
    help_line = re.sub(r'[%$]d', desc, help_line)

_say(emit, suffix=help_line, dob=item, s1=str(asking), s2=currency)

# ── Charge the interaction roundtime (merchant.rt) ───────────────────
# Haggling for a quote takes a beat; the do_wait gate at the top of this
# verb then blocks further buys until it counts down.  Defaults to 0, so
# a merchant with no rt set imposes no cooldown.
rt = getattr(merchant, 'rt', 0) or 0
if rt > 0:
    call_verb(pobj, '_rt', amount=rt)
