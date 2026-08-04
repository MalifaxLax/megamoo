"""
Brings a parsed LambdaMOO database into MegaMOO.

:mod:`moo.lambdamoo` reads the file; this maps what it read onto real
objects.  The split matters -- the reader can be pointed at a core without
creating anything, which is what makes a dry run honest.

What is imported
----------------

Objects, their parentage, their names, and their properties, with object
references remapped.  Verbs come across too, but **inert**: their code is
MOO, and MegaMOO runs Python.

Object numbers
--------------

A LambdaMOO ``#10`` cannot become a MegaMOO ``#10`` -- that number is
already the base object here, and half the core would land on top of the
shipped hierarchy.  Every imported object gets a fresh number, and a map
from old to new is built first, so that a property holding ``#57`` can be
rewritten to whatever ``#57`` became.  The original number is recorded on
each object as ``moo_import_id`` so a later pass can still find things.

References that point outside the import -- a negative object number, or
one the source database never had -- are left as they are and counted.
They cannot be remapped onto anything true, and silently pointing them at
a wrong object would be worse than leaving them visibly broken.

Properties
----------

LambdaMOO stores an object's property *values* positionally, in
inheritance order: every ancestor's definitions from the root down, then
the object's own.  The names are not repeated per object, so recovering
them means walking the parent chain and concatenating.  A value of
``clear`` means "inherit from the parent", which is exactly what an absent
MegaMOO property means, so those are skipped rather than written.

Verbs
-----

See :func:`build_inert_verb`.  Nothing imported can execute.
"""

import time
from typing import Dict, List, Optional

from .lambdamoo import (
    LambdaDB, LambdaObject, LambdaVerbDef, ObjRef,
    PF_READ, PF_WRITE, VF_READ, VF_WRITE, VF_EXEC, VF_DEBUG,
)

__all__ = ['import_lambda_db', 'build_inert_verb', 'property_names_for']


#: Marks an imported verb.  Anything scanning for un-ported code looks for
#: this line, so it is a constant rather than typed out in two places.
UNPORTED_MARKER = 'UNPORTED MOO SOURCE -- this verb does not run.'

#: Property recording where an object came from.
ORIGIN_PROP = 'moo_import_id'

#: Names a MegaMOO object handles itself.  A MOO property with one of
#: these names cannot be stored under it -- ``obj.flags = ...`` sets the
#: real flags word, not a property -- so those are renamed on the way in.
#: ``aliases`` is deliberately absent: MOO means the same thing by it that
#: MegaMOO does, so it is mapped onto the native attribute instead.
RESERVED_NAMES = frozenset({
    'children', 'contents', 'created', 'flags', 'last_move', 'location',
    'noun', 'objnum', 'owner', 'parent', 'properties', 'tags', 'verbs',
})


def safe_property_name(name: str):
    """
    Give a MOO property name that MegaMOO can actually store.

    Two kinds of name do not survive a direct write.  One is a name the
    object handles natively -- assigning ``flags`` sets the flags word
    rather than creating a property.  The other is anything starting with
    an underscore: those are Python instance attributes here, found by
    normal attribute lookup before the property system is consulted, so
    they would be invisible as properties and could shadow an internal.

    Both are prefixed rather than dropped.  A renamed property is still
    the data that was in the source database, and the report lists every
    rename so nothing changes name silently.

    Args:
        name: The property name from the source database.

    Returns:
        ``(stored_name, was_renamed)``.
    """
    if name.startswith('_'):
        # 'moo' + '_mail_task' -> 'moo_mail_task', still a valid identifier
        # and no longer underscore-led.
        return 'moo' + name, True
    if name in RESERVED_NAMES:
        return 'moo_' + name, True
    return name, False


def property_names_for(obj: LambdaObject, ldb: LambdaDB) -> List[str]:
    """
    Recover the property names matching an object's positional values.

    LambdaMOO writes values in inheritance order -- root ancestor's
    definitions first, then down the chain, then the object's own.  The
    names live only on the object that defined them, so the chain has to be
    walked to line names up with values.

    The ``seen`` guard is not paranoia: a damaged database can contain a
    parent cycle, and without it this loops forever.

    Args:
        obj: The object whose value list is being named.
        ldb: The database it came from, for resolving parents.

    Returns:
        Property names, in the same order as ``obj.propvals``.
    """
    chain, seen = [], set()
    node: Optional[LambdaObject] = obj
    while node is not None and node.objid not in seen:
        seen.add(node.objid)
        chain.append(node)
        node = ldb.objects.get(node.parent) if node.parent >= 0 else None

    names: List[str] = []
    for ancestor in reversed(chain):
        names.extend(ancestor.propdefs)
    return names


def _moo_perms(perms: int) -> str:
    """Render LambdaMOO verb permission bits the way MOO shows them."""
    out = ''.join([
        'r' if perms & VF_READ else '',
        'w' if perms & VF_WRITE else '',
        'x' if perms & VF_EXEC else '',
        'd' if perms & VF_DEBUG else '',
    ])
    return out or '(none)'


def build_inert_verb(verb: LambdaVerbDef, objid: int, when: str) -> str:
    """
    Wrap MOO source in a Python verb body that documents it and does nothing.

    The imported code is MOO and cannot run here, but throwing it away
    would throw away the only description of what the object was supposed
    to do.  So it is kept verbatim, as comments, under a docstring that
    says plainly what it is and how to port it.

    Comments rather than a string literal: MOO source contains quotes of
    every kind, including triple quotes, and a comment cannot be escaped
    out of.  Nothing in the body executes; the trailing ``return None``
    means that even if something contrives to call it, it does nothing.

    Args:
        verb:  The verb definition, with its ``code`` filled in.
        objid: The object number in the *source* database, for the header.
        when:  Timestamp string for the provenance line.

    Returns:
        Python source for the verb body.
    """
    names = verb.names or '(unnamed)'
    source = verb.code or '(this verb had no code in the source database)'

    header = f'''"""
{UNPORTED_MARKER}

Imported from a LambdaMOO database on {when}.

MegaMOO verbs are Python.  This is the original MOO-language source, kept
exactly as it was so it can be ported by hand.  Nothing runs it: the verb
is stored without the execute permission and hidden from both dispatch and
help, so it cannot be reached by a player typing its name.

Original
    object      #{objid}
    verb        {names}
    owner       #{verb.owner}
    permissions {_moo_perms(verb.perms)}
    called as   <{verb.dobj}> {verb.prep_name} <{verb.iobj}>

To port it: read the source below, write the Python equivalent here in its
place, then give the verb 'rx' permissions and an auth level.  Delete this
docstring when you do -- it is what marks the verb as un-ported.

The substitutions that cover most lines:

    player:tell("a", b)      ->  pobj.msg(f"a{{b}}")   or tell(pobj, "a", b)
    this:verbname(args)      ->  call_verb(this, 'verbname', args)
    pass(@args)              ->  pass_(*args)
    $string_utils:foo(x)     ->  su.foo(x)
    $object_utils:foo(x)     ->  ou.foo(x)
    #123                     ->  #123                (resolved on input)
    E_PERM                   ->  E_PERM              (a value here too)
    this.location            ->  this.location       (unchanged)
    args, argstr, dobj       ->  args, argstr, dobj  (unchanged)
    player                   ->  pobj
    caller_perms()           ->  caller
    typeof(x) == LIST        ->  isinstance(x, list)
    x in {{1, 2}}              ->  x in [1, 2]
    length(x)                ->  len(x)
    tostr(a, b)              ->  f"{{a}}{{b}}"

A MOO verb returns by assigning `result`, or with a bare `return`.  See
docs/guide/ and the README's "Porting from LambdaMOO" section for the rest.

--- original MOO source follows, as comments ---
"""
'''

    body = '\n'.join(f'# {line}' for line in source.split('\n'))
    return f"{header}\n{body}\n\nreturn None\n"


def import_lambda_db(ldb: LambdaDB, db, *, owner: int = 1,
                     root_parent: int = 1, dry_run: bool = False,
                     skip_players: bool = True) -> Dict:
    """
    Create MegaMOO objects for everything in a parsed LambdaMOO database.

    Args:
        ldb:          The parsed source database.
        db:           The MegaMOO ``Database`` to import into.
        owner:        Object number to own everything imported.
        root_parent:  What an object with no parent is parented to.
        dry_run:      Work out the whole mapping and report it without
                      creating anything.
        skip_players: Leave player objects out.  On by default: a player
                      object carries a password hash and a connection
                      history that mean nothing here, and importing one
                      creates an account nobody can log into.

    Returns:
        A report dict: counts, the old-to-new object map, and lists of
        anything that could not be brought across faithfully.
    """
    when = time.strftime('%Y-%m-%d')

    sources = [o for o in ldb.live_objects
               if not (skip_players and o.is_player)]

    report = {
        'dry_run': dry_run,
        'considered': len(ldb.live_objects),
        'skipped_players': len(ldb.live_objects) - len(sources),
        'objects': 0, 'properties': 0, 'verbs': 0,
        'objmap': {}, 'unresolved_refs': [], 'failures': [], 'renamed': {},
    }

    if dry_run:
        # Nothing is created, so there is no map to remap through; count
        # what would happen and stop.
        for src in sources:
            report['objects'] += 1
            names = property_names_for(src, ldb)
            for i, (value, _o, _p) in enumerate(src.propvals):
                if value is not None and i < len(names):
                    report['properties'] += 1
            report['verbs'] += len(src.verbs)
        return report

    # ---- pass 1: make every object, so references have something to hit --
    objmap: Dict[int, int] = {}
    for src in sources:
        try:
            new = db.create_object(parent=root_parent, owner=owner)
        except Exception as err:
            report['failures'].append(f"#{src.objid}: could not create ({err})")
            continue
        objmap[src.objid] = new.objnum
        report['objects'] += 1
    report['objmap'] = objmap

    def remap(value):
        """Rewrite object references; recurse into lists."""
        if isinstance(value, ObjRef):
            target = objmap.get(int(value))
            if target is None:
                report['unresolved_refs'].append(int(value))
                return int(value)
            return f'#{target}'
        if isinstance(value, list):
            return [remap(v) for v in value]
        return value

    # ---- pass 2: parentage, names, properties, verbs ---------------------
    from .verbs import VerbDef

    for src in sources:
        num = objmap.get(src.objid)
        if num is None:
            continue
        obj = db.get_object(num)

        parent_num = objmap.get(src.parent, root_parent)
        try:
            obj.parent = parent_num
        except Exception as err:
            report['failures'].append(f"#{src.objid}: parent ({err})")

        if src.name:
            obj.noun = src.name.split()[0] if src.name.split() else src.name

        names = property_names_for(src, ldb)
        for i, (value, _powner, pperms) in enumerate(src.propvals):
            if i >= len(names):
                break
            # A clear value means "inherit", which is what an absent
            # MegaMOO property already means.  Writing it would turn an
            # inherited value into a local None.
            if value is None:
                continue
            perms = ''.join(['r' if pperms & PF_READ else '',
                             'w' if pperms & PF_WRITE else '']) or 'r'

            pname = names[i]
            mapped = remap(value)

            # MOO's aliases and MegaMOO's mean the same thing, so this one
            # collision resolves onto the native attribute rather than into
            # a renamed property.  Only when it really is a list of names --
            # a few cores keep something else there.
            if pname == 'aliases':
                if isinstance(mapped, list) and all(isinstance(x, str)
                                                    for x in mapped):
                    try:
                        obj.aliases = list(mapped)
                        report['properties'] += 1
                    except Exception as err:
                        report['failures'].append(f"#{src.objid}.aliases: {err}")
                    continue
                pname = 'moo_aliases'
                report['renamed'].setdefault('aliases', 'moo_aliases')

            stored, was_renamed = safe_property_name(pname)
            if was_renamed:
                report['renamed'].setdefault(pname, stored)

            try:
                obj.add_property(stored, mapped, perms=perms + 'c')
                report['properties'] += 1
            except Exception as err:
                report['failures'].append(f"#{src.objid}.{stored}: {err}")

        if src.name:
            try:
                obj.add_property('name', src.name, perms='rc')
            except Exception:
                pass
        try:
            obj.add_property(ORIGIN_PROP, src.objid, perms='rc')
        except Exception:
            pass

        for verb in src.verbs:
            vnames = verb.name_list or ['unnamed']
            # LambdaMOO marks minimum-match with '*' inside the name
            # ("ex*amine" matches "ex" through "examine").  Keep the full
            # word and record where the star was.
            clean, mins = [], {}
            for raw in vnames:
                if '*' in raw:
                    before, _, after = raw.partition('*')
                    word = before + after
                    clean.append(word)
                    mins[word] = len(before)
                else:
                    clean.append(raw)
            try:
                vd = VerbDef(
                    names=clean,
                    code=build_inert_verb(verb, src.objid, when),
                    owner=owner,
                    # No 'x': an un-ported verb must not be executable.
                    perms='r',
                    min_lengths=mins,
                    # Hidden keeps it out of dispatch and out of help.
                    hidden=True,
                    auth=3,
                )
                obj.add_verb(vd)
                report['verbs'] += 1
            except Exception as err:
                report['failures'].append(
                    f"#{src.objid}:{clean[0]}: {err}")

        try:
            db.save_object(obj)
        except Exception as err:
            report['failures'].append(f"#{src.objid}: save ({err})")

    report['unresolved_refs'] = sorted(set(report['unresolved_refs']))
    return report
