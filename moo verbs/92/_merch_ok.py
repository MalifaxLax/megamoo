"""
_merch_ok helper on #92 (BaseMerchant) -- hidden.

Decide whether this merchant will sell <citem> in the requested
quantity.  Called by the room buy verb:

    call_verb(merchant, '_merch_ok', citem=<obj>, cqtype='single'|'case'|'halfcase')

Returns '' if the sale is allowed, otherwise a short refusal line for
the buy verb to speak.  `pobj` is the buyer, `this` is the merchant.

For now the only rule is case_exclude: some goods (open glasses of
liquid, etc.) can't be bought by the case/half-case.  case_exclude is a
list of stock objnums (the item, or the liquid type it holds).
"""

it = citem

if cqtype != 'single':
    excl = getattr(this, 'case_exclude', None) or []
    lt = getattr(it, 'ltype', None)
    if it.objnum in excl or (lt and hasattr(lt, 'objnum') and lt.objnum in excl):
        return "That's not something I'll sell by the case."

return ''
