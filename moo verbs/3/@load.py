"""
Builds an object from a file written by @dump.

Usage: @load <file>
       @load/list

Arguments:
    file - A file in the dumps/ directory.  The .json may be left off.

Switches:
    /list - Show what is available to load.
    /dry  - Report what would be built without building it.

Auth: gm3+ (auth_level 3)

The loaded object is always a *new* object with a new number.  Nothing is
overwritten, because the number in the dump belongs to whatever holds it
here, which is rarely the same thing.

Two things are worth knowing before moving content between databases:

Parent.  The dump records a parent by number, and that number means
whatever it means *here*.  Loading a dump from another database against a
mismatched hierarchy is the one way to get a badly wrong result, so the
parent is named in the output -- check it.

Object references.  A property holding #N is stored as a number, and the
number is not remapped, because there is nothing to remap it to.  These
are counted and listed, so they can be fixed by hand with @set.

See also: @dump
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

import json
import os

folder = os.path.join(os.getcwd(), 'dumps')

if 'list' in switches:
    try:
        files = sorted(f for f in os.listdir(folder) if f.endswith('.json'))
    except Exception:
        files = []
    pobj.msg("")
    if not files:
        pobj.msg(f"Nothing in {folder}.")
        return
    pobj.msg(f"&<245>In {folder}:&n")
    pobj.msg("")
    for name in files:
        size = os.path.getsize(os.path.join(folder, name))
        pobj.msg(f"  {name}  &<245>({size} bytes)&n")
    pobj.msg("")
    pobj.msg(f"&<245>-- {len(files)} file{'' if len(files) == 1 else 's'}.&n")
    return

spec = (args or '').strip()
if not spec:
    pobj.msg('Usage: @load <file>')
    pobj.msg('Example: @load 92-BaseMerchant')
    pobj.msg('Use @load/list to see what is there.')
    return

if not spec.endswith('.json'):
    spec += '.json'

# Keep the read inside dumps/.  A gm3 can reach the disk by other means,
# so this is tidiness rather than a barrier -- but a stray '..' in a
# filename should not quietly read something else.
path = os.path.normpath(os.path.join(folder, spec))
if not path.startswith(folder + os.sep):
    pobj.msg("That is not in the dumps directory.")
    return

try:
    with open(path) as fh:
        record = json.load(fh)
except FileNotFoundError:
    pobj.msg(f"No such file: {spec}")
    pobj.msg("Use @load/list to see what is there.")
    return
except Exception as err:
    pobj.msg(f"Could not read {spec}: {err}")
    return

if not isinstance(record, dict) or not record.get('megamoo_dump'):
    pobj.msg("That is not a MegaMOO dump.")
    return

body = record.get('object') or {}
props = body.get('properties') or {}
verbs = body.get('verbs') or []

parent_num = body.get('parent') or 0
try:
    parent = db.get_object(parent_num) if parent_num else None
except Exception:
    parent = None
if parent_num and parent is None:
    pobj.msg(f"This dump wants parent #{parent_num}, which does not exist here.")
    return

# Object references travel as bare numbers and mean nothing in a database
# that did not write them.  Find them so they can be reported.
dangling = []
for pname, pinfo in props.items():
    value = (pinfo or {}).get('value')
    if isinstance(value, str) and value.startswith('#') and value[1:].isdigit():
        # A missing object raises rather than returning None -- which is
        # precisely the case being looked for here.
        try:
            found = db.get_object(int(value[1:]))
        except Exception:
            found = None
        if found is None:
            dangling.append(f"{pname} -> {value}")

if 'dry' in switches:
    pobj.msg("")
    pobj.msg(f"&<245>Would build from {spec}:&n")
    pobj.msg("")
    pobj.msg(f"  name    {record.get('name') or '?'}")
    pobj.msg(f"  parent  #{parent_num}:{parent.name if parent else 'none'}")
    pobj.msg(f"  props   {len(props)}")
    pobj.msg(f"  verbs   {len(verbs)}")
    if dangling:
        pobj.msg("")
        pobj.msg(f"  &<245>{len(dangling)} reference(s) point at objects "
                 f"that are not here:&n")
        for item in dangling[:8]:
            pobj.msg(f"    {item}")
    return

new = create(parent_num, owner=pobj.objnum)
if new is None:
    pobj.msg("Could not create the object.")
    return

if body.get('noun'):
    new.noun = body['noun']
if body.get('aliases'):
    new.aliases = list(body['aliases'])
if body.get('flags'):
    new.flags = body['flags']

made = 0
failed = []
for pname, pinfo in props.items():
    pinfo = pinfo or {}
    try:
        add_property(new, pname, pinfo.get('value'),
                     perms=pinfo.get('perms') or 'rc')
        made += 1
    except Exception as err:
        failed.append(f"{pname}: {err}")

added = 0
for vinfo in verbs:
    names = list(vinfo.get('names') or [])
    if not names:
        continue
    try:
        # Built directly rather than through add_verb(), which creates the
        # verb with empty code and has nowhere to put it back.
        from moo.verbs import VerbDef
        vd = VerbDef(names=names,
                     code=vinfo.get('code') or '',
                     owner=new.owner,
                     perms=vinfo.get('perms') or 'rx',
                     parent_type=(vinfo.get('parent_type')
                                  or 'moo.verb_types.MasterVerb'),
                     min_lengths=dict(vinfo.get('min_lengths') or {}),
                     hidden=bool(vinfo.get('hidden')),
                     auth=vinfo.get('auth') or 0)
        new.add_verb(vd)
        added += 1
    except Exception as err:
        failed.append(f"verb {names[0]}: {err}")

db.save_object(new)

pobj.msg("")
pobj.msg(f"Loaded {spec} as #{new.objnum}:{new.name}")
pobj.msg(f"  &<245>parent #{parent_num}:{parent.name if parent else 'none'}, "
         f"{made} propert{'y' if made == 1 else 'ies'}, "
         f"{added} verb{'' if added == 1 else 's'}.&n")

if dangling:
    pobj.msg("")
    pobj.msg(f"  &<245>{len(dangling)} reference(s) point at objects that are "
             f"not in this database; fix with @set:&n")
    for item in dangling[:8]:
        pobj.msg(f"    {item}")

if failed:
    pobj.msg("")
    pobj.msg(f"  &<245>{len(failed)} did not apply:&n")
    for item in failed[:8]:
        pobj.msg(f"    {item}")
