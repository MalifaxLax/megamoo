"""
Renumbers an object, in place.

Usage: @renumber <object> [= | to] [<new_number>]

Arguments:
    object      - The object to renumber (matched in room and inventory).
    new_number  - Optional target number. Defaults to the lowest available.

The object's rows are moved rather than deleted and rebuilt, so the live
object keeps its identity -- anything already holding it, a running verb
or a ticker subscription, keeps a working reference instead of a
discarded copy. Nine columns in the schema name an object number and all
nine follow it: the object, its properties, its verbs, its children, its
contents, the objects, properties and verbs it owns, and its login name.

Three kinds of reference live outside those columns, and are handled
here:

    verb files   <moo_verb_path>/<objnum>/ is renamed, or the object
                 arrives at its new number with no source on disk and
                 the watcher reloads it onto nothing.

    "#N" values  a property whose value is the string "#<old>" is
                 rewritten wherever it appears. That spelling is only
                 ever an object reference, so it is always safe.

    listed refs  the property names in $objref_props hold object numbers
                 as bare integers. Those are rewritten too, at any depth.

Everything else that still names the old number is reported, not guessed
at. `obvexits` is the reason: it holds direction indices, so [1, 2, 3]
there means north, south and east -- not #1, #2 and #3. Since #0 to #40
are all real objects, no test on a value can tell a small number from a
reference to a low object. This is the same line LambdaMOO's renumber()
draws when it declines to touch property values at all, and its cores
fix a short hand-written list afterwards exactly as $objref_props does.

Auth: gm5 (auth_level 5)
"""
if auth_level(pobj) < 5:
    pobj.msg("Do what?")
    return

if not dobj:
    pobj.msg('Usage: @renumber <object> [= | to] [<new number>]')
    pobj.msg('Example: @renumber #42 = #8')
    pobj.msg('Example: @renumber #42 to #8')
    pobj.msg('Example: @renumber #42')
    return

# Property names whose values hold object numbers as bare integers.
# Overridable per world via $objref_props; this is the fallback, and it
# deliberately leaves out anything whose numbers are not references --
# obvexits (direction indices), every stat and skill list, and merchant
# vessels, whose entries pair a prototype with a multiplier that a blind
# rewrite would corrupt. What is left out is reported instead.
DEFAULT_OBJREF_PROPS = [
    'exits', 'dexits', 'destination', 'rexit', 'reverse',
    'in_exit', 'on_exit', 'under_exit', 'behind_exit', 'through_exit',
    'in_contents', 'on_contents', 'under_contents', 'behind_contents',
    'characters', 'marks', 'wearing', 'plist', 'sitters', 'table',
    'last_location', 'home',
]

candidates = list(pobj.contents) + list(pobj.location.contents)
old_obj = bmatch(dobj, pobj, candidates, db)
if not old_obj:
    pobj.msg(f"Object '{dobj}' not found.")
    return
old_num = old_obj.objnum

# Lowest unassigned number, which is also the default target.
if db._index.recycled_objects:
    lowest_available = min(db._index.recycled_objects)
else:
    lowest_available = db._index.next_objnum

if iobj and prep in ('=', 'to'):
    try:
        new_num = int(iobj.strip().lstrip('#'))
    except ValueError:
        pobj.msg(f"Invalid object number: {iobj}")
        return
else:
    new_num = lowest_available

if new_num < 0:
    pobj.msg("Object number must be non-negative.")
    return
if new_num == old_num:
    pobj.msg(f"#{old_num} is already at that number.")
    return

# Refuse to open a gap: an unassigned target is only allowed if it is the
# lowest one free, or if something is already sitting above it.
if not db.valid(new_num) and new_num != lowest_available:
    has_objects_above = False
    for n in range(new_num + 1, db._index.next_objnum):
        if db.valid(n):
            has_objects_above = True
            break
    if not has_objects_above:
        pobj.msg(f"#{lowest_available} is the lowest unassigned number.")
        return

# An occupied target has to be cleared first, and only with permission.
if db.valid(new_num):
    existing = db.get_object(new_num)
    answer = yield f"#{new_num} ({existing.name}) already exists. Delete it? [y/n] "
    if answer.strip().lower() not in ('y', 'ye', 'yes'):
        pobj.msg("Cancelled.")
        return
    if existing.children:
        pobj.msg(f"Cannot delete #{new_num}: it has children {existing.children}.")
        return
    if existing._content_ids:
        pobj.msg(f"Cannot delete #{new_num}: it has contents. Move them first.")
        return
    existing_name = existing.name
    recycle(existing)
    pobj.msg(f"Deleted &<245>#{new_num}:{existing_name}&n.")

# --- 1. Move the object ---------------------------------------------------
try:
    counts = db.renumber_object(old_num, new_num)
except Exception as e:
    pobj.msg(f"Renumber failed: {e}")
    return

moved = ', '.join(f'{k} x{v}' for k, v in counts.items() if v)
pobj.msg(f"&<245>#{old_num}&n is now &<245>#{new_num}:{db.get_object(new_num).name}&n.")
pobj.msg(f"&<245>Moved: {moved}&n")

# --- 2. Move the verb source ----------------------------------------------
import os

try:
    from moo.verb_loader import resolve_verb_base_path
    base = resolve_verb_base_path(db)
except Exception:
    base = None

if base:
    src = os.path.join(base, str(old_num))
    dst = os.path.join(base, str(new_num))
    if os.path.isdir(src):
        if os.path.exists(dst):
            pobj.msg(f"&<245>Verb files: {dst} already exists -- left {src} alone.&n")
        else:
            try:
                os.rename(src, dst)
                n_files = len([f for f in os.listdir(dst) if f.endswith('.py')])
                pobj.msg(f"&<245>Verb files: moved {n_files} file(s) to {new_num}/&n")
            except Exception as e:
                pobj.msg(f"&<245>Verb files: could not move {src}: {e}&n")

# --- 3. Rewrite the references we can be sure about ------------------------
objref_props = getattr(db.get_object(0), 'objref_props', None) or DEFAULT_OBJREF_PROPS
old_ref = f'#{old_num}'
new_ref = f'#{new_num}'


def remap(value, listed):
    """
    Return (new_value, changed).

    A whole-value "#N" string is a reference by construction and is always
    rewritten. A bare integer is only a reference when the property was
    named as one, so that rewrite is gated on `listed`.
    """
    if isinstance(value, str):
        return (new_ref, True) if value == old_ref else (value, False)
    if isinstance(value, bool):
        return value, False
    if isinstance(value, int):
        if listed and value == old_num:
            return new_num, True
        return value, False
    if isinstance(value, list):
        out, hit = [], False
        for item in value:
            item, ch = remap(item, listed)
            out.append(item)
            hit = hit or ch
        return (out, True) if hit else (value, False)
    if isinstance(value, dict):
        out, hit = {}, False
        for k, item in value.items():
            item, ch = remap(item, listed)
            out[k] = item
            hit = hit or ch
        return (out, True) if hit else (value, False)
    return value, False


def mentions(value):
    """Does this value still name the old number anywhere in it?"""
    if isinstance(value, str):
        return value == old_ref
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value == old_num
    if isinstance(value, list):
        return any(mentions(v) for v in value)
    if isinstance(value, dict):
        return any(mentions(v) for v in value.values())
    return False


fixed = []
for obj in list(db.objects()):
    for pname in list(obj.properties.keys()):
        info = obj.properties[pname]
        value, changed = remap(info.value, pname in objref_props)
        if changed:
            obj.properties[pname].value = value
            obj._all_dirty = True
            db.save_object(obj)
            fixed.append(f'#{obj.objnum}.{pname}')

if fixed:
    pobj.msg(f"&<245>Rewrote {len(fixed)}: {', '.join(fixed[:12])}"
             + (' ...' if len(fixed) > 12 else '') + '&n')

# --- 4. Report whatever is left -------------------------------------------
left = []
for obj in list(db.objects()):
    for pname, info in obj.properties.items():
        if mentions(info.value):
            left.append(f'#{obj.objnum}.{pname} = {info.value}')

if left:
    pobj.msg(f"Still naming {old_num} -- check these by hand:")
    for line in left[:20]:
        pobj.msg(f"  {line}")
    if len(left) > 20:
        pobj.msg(f"  ... and {len(left) - 20} more")
else:
    pobj.msg(f"&<245>Nothing else names {old_num}.&n")
