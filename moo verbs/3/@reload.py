"""
Usage: @reload <object>.<verb_name_or_path>
       @reload <object>
       @reload all

Reloads a verb's code from a file on disk.

If the verb part contains '/', it is treated as a path to the
file. The verb name is derived from the last path component.

Otherwise, the file is looked up in the per-object directory
first: <moo_verb_path>/<objnum>/<verb_name>.py, then falls
back to <moo_verb_path>/<verb_name>.py.

If the per-object directory doesn't exist, it is created and
all verbs on the object are exported into it.

The .py extension is always added automatically.

@reload all scans all <moo_verb_path>/<objnum>/ directories
and loads every verb file found. Verbs that exist on the object
are updated; verbs that don't exist yet are created.

Examples:
    @reload #7.go_
    @reload #3.@move
    @reload all
"""
import os
from moo.verbs import VerbDef

if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if not args:
    pobj.msg("Usage: @reload <object>.<verb_name_or_path>  or  @reload all")
    return

# Resolve base verb path from #8.moo_verb_path
verb_path = getattr(db.get_object(8), 'moo_verb_path', None)
if not verb_path:
    pobj.msg("#8.moo_verb_path is not set.")
    return
from moo.verb_loader import expand_verb_path
base_path = expand_verb_path(verb_path)

# --- @reload all ---
if args.strip().lower() == 'all':
    updated = 0
    created = 0
    errors = 0
    for entry in sorted(os.listdir(base_path)):
        obj_dir = os.path.join(base_path, entry)
        if not os.path.isdir(obj_dir) or not entry.isdigit():
            continue
        objnum = int(entry)
        try:
            obj = db.get_object(objnum)
        except Exception:
            pobj.msg(f"%<196>Object #{objnum} not found in database — skipping.%n")
            errors += 1
            continue
        for fname in sorted(os.listdir(obj_dir)):
            if not fname.endswith('.py'):
                continue
            verb_name = fname[:-3]
            filepath = os.path.join(obj_dir, fname)
            try:
                code = open(filepath).read()
            except Exception as e:
                pobj.msg(f"%<196>Error reading {filepath}: {e}%n")
                errors += 1
                continue
            # Skip empty/comment-only files
            stripped = '\n'.join(l for l in code.splitlines() if l.strip() and not l.strip().startswith('#'))
            if not stripped.strip():
                continue
            # Find existing verb
            matches = [v for v in obj.verbs if verb_name in v.names]
            if matches:
                v = matches[0]
                v.code = code
                v.compiled_code = None
                try:
                    v.compile()
                    updated += 1
                except Exception as e:
                    pobj.msg(f"%<196>Compile error: #{objnum}.{verb_name}: {e}%n")
                    errors += 1
                    continue
            else:
                # Create new verb
                try:
                    vd = VerbDef(names=[verb_name], code=code, owner=obj.owner, perms='rx')
                    obj.add_verb(vd)
                    created += 1
                except Exception as e:
                    pobj.msg(f"%<196>Error creating #{objnum}.{verb_name}: {e}%n")
                    errors += 1
                    continue
        obj._mark_modified()
    pobj.msg(f"Reload all: %<245>{updated}%n updated, %<245>{created}%n created, %<196>{errors}%n errors.")
    return

# --- Reload all verbs on one object: @reload #N ---
dot = args.find('.')
if dot < 0:
    obj_ref = args.strip()
    if obj_ref.startswith('#') and obj_ref[1:].isdigit():
        try:
            obj = db.get_object(int(obj_ref[1:]))
        except Exception:
            pobj.msg(f"Object {obj_ref} not found.")
            return
    else:
        obj = bmatch(obj_ref, pobj, list(pobj.location.contents) + list(pobj.contents), db)
        if not obj:
            pobj.msg(f"Object '{obj_ref}' not found.")
            return
    obj_dir = os.path.join(base_path, str(obj.objnum))
    if not os.path.isdir(obj_dir):
        pobj.msg(f"No verb directory for #{obj.objnum}.")
        return
    updated = 0
    created = 0
    errors = 0
    for fname in sorted(os.listdir(obj_dir)):
        if not fname.endswith('.py'):
            continue
        verb_name = fname[:-3]
        filepath = os.path.join(obj_dir, fname)
        try:
            code = open(filepath).read()
        except Exception as e:
            pobj.msg(f"%<196>Error reading {filepath}: {e}%n")
            errors += 1
            continue
        stripped = '\n'.join(l for l in code.splitlines() if l.strip() and not l.strip().startswith('#'))
        if not stripped.strip():
            continue
        matches = [v for v in obj.verbs if verb_name in v.names]
        if matches:
            v = matches[0]
            v.code = code
            v.compiled_code = None
            try:
                v.compile()
                updated += 1
            except Exception as e:
                pobj.msg(f"%<196>Compile error: #{obj.objnum}.{verb_name}: {e}%n")
                errors += 1
                continue
        else:
            try:
                vd = VerbDef(names=[verb_name], code=code, owner=obj.owner, perms='rx')
                obj.add_verb(vd)
                created += 1
            except Exception as e:
                pobj.msg(f"%<196>Error creating #{obj.objnum}.{verb_name}: {e}%n")
                errors += 1
                continue
    obj._mark_modified()
    pobj.msg(f"Reload #{obj.objnum}: %<245>{updated}%n updated, %<245>{created}%n created, %<196>{errors}%n errors.")
    return

# --- Single verb reload ---

obj_ref = args[:dot].strip()
verb_part = args[dot + 1:].strip()

if not obj_ref or not verb_part:
    pobj.msg("Usage: @reload <object>.<verb_name_or_path>")
    return

# Resolve object
if obj_ref.startswith('#') and obj_ref[1:].isdigit():
    try:
        obj = db.get_object(int(obj_ref[1:]))
    except Exception:
        pobj.msg(f"Object {obj_ref} not found.")
        return
else:
    obj = bmatch(obj_ref, pobj, list(pobj.location.contents) + list(pobj.contents), db)
    if not obj:
        pobj.msg(f"Object '{obj_ref}' not found.")
        return

# Determine if verb_part is a path or a verb name
if '/' in verb_part:
    # Path form: derive verb name from last component
    verb_name = os.path.basename(verb_part)
    filepath = verb_part + '.py'
else:
    verb_name = verb_part
    obj_dir = os.path.join(base_path, str(obj.objnum))

    # If the per-object directory doesn't exist, create it and
    # export all verbs on this object into it
    if not os.path.isdir(obj_dir):
        os.makedirs(obj_dir, exist_ok=True)
        exported = 0
        for v in obj.verbs:
            vn = v.names[0] if v.names else None
            if vn and v.code:
                vfile = os.path.join(obj_dir, vn + '.py')
                try:
                    with open(vfile, 'w') as f:
                        f.write(v.code)
                    exported += 1
                except Exception:
                    pass
        if exported:
            pobj.msg(f"Created %<245>{obj_dir}%n — exported {exported} verb(s).")

    # Primary: per-object directory
    filepath = os.path.join(obj_dir, verb_name + '.py')

    # Fallback: flat directory
    if not os.path.isfile(filepath):
        flat = os.path.join(base_path, verb_name + '.py')
        if os.path.isfile(flat):
            filepath = flat

# Read the file
if not os.path.isfile(filepath):
    pobj.msg(f"File not found: {filepath}")
    return

try:
    code = open(filepath).read()
except Exception as e:
    pobj.msg(f"Error reading file: {e}")
    return

# Find the verb on the object, or create it
matches = [v for v in obj.verbs if verb_name in v.names]
if matches:
    v = matches[0]
    v.code = code
    v.compiled_code = None
    v.compile()
    obj._mark_modified()
    pobj.msg(f"Reloaded %<245>{verb_name}%n on %<245>#{obj.objnum}:{obj.noun}%n from {filepath}")
else:
    vd = VerbDef(names=[verb_name], code=code, owner=obj.owner, perms='rx')
    obj.add_verb(vd)
    pobj.msg(f"Created %<245>{verb_name}%n on %<245>#{obj.objnum}:{obj.noun}%n from {filepath}")
