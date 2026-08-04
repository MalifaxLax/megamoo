"""
Duplicates an object: same parent, same name parts, same local properties.

Usage: @copy <object> [= <new name>]
       @copy <object> [= <new name>] times <count>

Arguments:
    object    - The object to copy (#objnum, $constant, or a name matched
                in the room or your inventory).
    new name  - Optional noun for the copy. Defaults to the original's.
    count     - Optional number of copies (after 'times'). Max 50.

Switches:
    /drop  - Leave the copies in the room instead of your inventory.

Auth: gm3+ (auth_level 3)

Copies the object's *own* properties, not inherited ones -- the copy has
the same parent, so it inherits the same things the original does. Verbs
are not copied for the same reason: behaviour belongs on the parent, and a
copy carrying its own duplicate of a verb is how a world drifts out of
sync with itself.

Contents are not copied either. Copying a chest gives you an empty chest,
not its contents; that is nearly always what was meant, and the exception
is easier to do by hand than to undo.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if not dobj:
    pobj.msg('Usage: @copy <object> [= <new name>] [times <count>]')
    pobj.msg('Example: @copy lantern')
    pobj.msg('Example: @copy lantern = lamp')
    pobj.msg('Example: @copy/drop #412 times 12')
    return

# How many copies? A trailing 'times N'.
#
# Pulled off the argument string by hand rather than read from prep2/dobj2:
# 'times' is not one of the parser's prepositions, so it would otherwise be
# swallowed into the object name and the match would fail.
count = 1
_target = (dobj or '').strip()
_tail = (iobj or '').strip() if prep == '=' else ''
_scan = _tail if _tail else _target
_words = _scan.split()
if len(_words) >= 2 and _words[-2].lower() == 'times' and _words[-1].isdigit():
    count = int(_words[-1])
    _scan = ' '.join(_words[:-2]).strip()
    if _tail:
        _tail = _scan
    else:
        _target = _scan
    if count < 1:
        pobj.msg("Count must be at least 1.")
        return
    if count > 50:
        pobj.msg("50 at a time is the limit; run it again for more.")
        return

if not _target:
    pobj.msg('Usage: @copy <object> [= <new name>] [times <count>]')
    return

candidates = list(pobj.location.contents) + list(pobj.contents)
source = bmatch(_target, pobj, candidates, db)
if not source:
    pobj.msg(f"Object '{_target}' not found.")
    return

new_noun = _tail if _tail else (source.noun or None)

# The source's own properties. Inherited ones are deliberately skipped:
# the copy shares the parent, so it already has them, and duplicating them
# locally would silently detach the copy from later edits to the parent.
own_props = source.properties_list(include_inherited=False, database=db)
skip = ('name', 'cname')  # rebuilt from the name parts by make_object

made = []
for _ in range(count):
    copy = ou.make_object(db.get_object(source.parent), db, pobj,
                          noun=new_noun, owner=pobj)
    for prop in own_props:
        if prop in skip:
            continue
        try:
            value = source.get_property_info(prop, db).value
        except Exception:
            continue
        try:
            copy.set_property(prop, value)
        except Exception:
            copy.add_property(prop, value)

    if 'drop' in switches:
        copy.move_to(pobj.location, db)
    else:
        copy.move_to(pobj, db)
    db.save_object(copy)
    made.append(copy)

where = 'here' if 'drop' in switches else 'in your inventory'
if len(made) == 1:
    c = made[0]
    pobj.msg(f"Copied %<245>#{source.objnum}:{source.name}%n to "
             f"%<245>#{c.objnum}:{c.name}%n, {where}.")
else:
    first, last = made[0], made[-1]
    pobj.msg(f"Made {len(made)} copies of %<245>#{source.objnum}:{source.name}%n, "
             f"%<245>#{first.objnum}%n-%<245>#{last.objnum}%n, {where}.")
