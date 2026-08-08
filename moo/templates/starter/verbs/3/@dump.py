"""
Writes an object out as text, so it can be moved or kept.

Usage: @dump <object>
       @dump/screen <object>

Arguments:
    object - The object to write out.

Switches:
    /screen - Print to the screen instead of writing a file.  Only
              sensible for small objects; a verb-bearing one is long.
    /verbs  - Include verb code.  Off by default, because it is the
              bulk of most dumps and the verb files on disk are usually
              the real source.

Auth: gm3+ (auth_level 3)

Writes to dumps/#<objnum>-<name>.json under the server directory.

What is written is what makes an object *itself*: parent, owner, flags,
noun, aliases, properties, and optionally verbs.  What is deliberately
left out is where it happens to be -- location, contents and children are
relationships to other objects, and they will not mean the same thing in
the database this is loaded into.

Verb metadata is read off the live VerbDef rather than its to_dict(),
which drops auth, hidden and min_lengths.  A verb reloaded without its
auth level is a verb that quietly stops being staff-only.

See also: @load
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

import json
import os
import time

spec = (args or '').strip()
if not spec:
    pobj.msg('Usage: @dump <object>')
    pobj.msg('Example: @dump #92')
    pobj.msg('Example: @dump/screen #12')
    return

candidates = list(pobj.location.contents) + list(pobj.contents)
target = bmatch(spec, pobj, candidates, db)
if target is None and spec.startswith('#') and spec[1:].isdigit():
    # get_object raises for a number nobody holds, rather than
    # returning None, so the report below never got reached.
    try:
        target = db.get_object(int(spec[1:]))
    except Exception:
        target = None
if target is None:
    pobj.msg(f"'{spec}' not found.")
    return

raw = target.to_dict()

# Relationships, not identity.  A dump loaded elsewhere would point these
# at whatever happens to hold those numbers in the target database.
for key in ('location', 'contents', 'children', 'created', 'last_move'):
    raw.pop(key, None)

record = {
    'megamoo_dump': 1,
    'dumped': time.strftime('&Y-&m-%dT&H:&M:&S'),
    'objnum': target.objnum,
    'name': str(target.name or ''),
    'object': raw,
}

if 'verbs' in switches:
    verbs = []
    for v in list(target.verbs or []):
        names = list(v.names or [])
        if not names:
            continue
        verbs.append({
            'names': names,
            'code': v.code or '',
            'owner': v.owner or 0,
            'perms': v.perms or 'rx',
            # Read off the VerbDef, not to_dict(), which omits these three.
            'auth': v.auth or 0,
            'hidden': bool(v.hidden),
            'min_lengths': dict(v.min_lengths or {}),
            'parent_type': v.parent_type or '',
        })
    record['object']['verbs'] = verbs
else:
    record['object'].pop('verbs', None)

text = json.dumps(record, indent=2, sort_keys=True, default=str)

if 'screen' in switches:
    pobj.msg("")
    for line in text.splitlines():
        # Raw JSON on a colour-processing channel: % is the escape
        # character, so it has to be doubled or the output is mangled.
        pobj.msg(line.replace('&', '&&'))
    return

slug = ''.join(ch if ch.isalnum() else '-' for ch in str(target.name or 'object'))
slug = '-'.join(part for part in slug.split('-') if part)[:40] or 'object'

folder = os.path.join(os.getcwd(), 'dumps')
try:
    os.makedirs(folder, exist_ok=True)
except Exception as err:
    pobj.msg(f"Could not make {folder}: {err}")
    return

path = os.path.join(folder, f"{target.objnum}-{slug}.json")
try:
    with open(path, 'w') as fh:
        fh.write(text)
except Exception as err:
    pobj.msg(f"Could not write {path}: {err}")
    return

nprops = len(record['object'].get('properties') or {})
nverbs = len(record['object'].get('verbs') or [])

pobj.msg("")
pobj.msg(f"Dumped #{target.objnum}:{target.name} to")
pobj.msg(f"  &<245>{path}&n")
pobj.msg(f"  &<245>{nprops} propert{'y' if nprops == 1 else 'ies'}, "
         f"{nverbs} verb{'' if nverbs == 1 else 's'}"
         f"{'' if 'verbs' in switches else ' (use /verbs for code)'}.&n")
