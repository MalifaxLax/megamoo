"""
_ctitle verb on #28 (CupContainer).

Normalize a cup's display name to the VESSEL alone -- noun plus
name_mod_list [article, adj1, adj2, adj3, trailer] (e.g. noun 'glass',
adjective 'shot' -> "a shot glass").  The liquid never appears in the
title, full or empty: a shot glass may hold fire whiskey, but it isn't
named for it.  What's inside shows on `look`, not in the name.

Matching follows the name: a filled glass answers to "glass" / "shot
glass" (and pmatch prefixes), NOT to "whiskey" -- `drink whiskey` is a
miss by design.  (Merchant matching is unaffected: a poured-to-order
`buy whiskey` matches the stocked LIQUID object, never a cup.)

Call after any change to ltype (minting stock, filling, drinking dry)
-- it strips the liquid trailer any legacy cup may still carry, then
regenerates name/cname via _title.
"""

nml = list(this.name_mod_list or [])
while len(nml) < 5:
    nml.append('')
nml[4] = ''
this.name_mod_list = nml
call_verb(this, '_title')
