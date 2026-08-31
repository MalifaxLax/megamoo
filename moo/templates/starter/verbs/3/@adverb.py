"""
Usage: @adverb[/hidden] <object>.<name[(min)][,...]> [with <perms> [base] [min=N] [auth=N]]

Adds a new verb to an object. Verb names can include minimum abbreviation
lengths in parentheses. Multiple aliases are separated by commas.

Switches:
    /hidden  - Add the verb, then hide it (not invokable by players).
    /hide    - Alias of /hidden.

Options (after 'with'):
    <perms>  - Permission string (default: 'rx'). Common values: rx, rwx, x.
    base     - Use BaseVerb parent type instead of MasterVerb.
    min=N    - Minimum abbreviation length for every name.
    auth=N   - Minimum auth level required (1-5, default: 0).

A per-name minimum also works, in parentheses: `examine(3)` sets one for
that name alone, and overrides min=N.

@min and @verbauth set the same two things on a verb that already exists.

Examples:
    @adverb #43.look,l
    @adverb #2.examine(3),look(1),l
    @adverb #2.examine,x with rx min=3
    @adverb #11.reset with rwx base
    @adverb/hidden #5.at_post_move
    @adverb #3.@telq with rx auth=3

Abbrev:  @adverb=4
Auth: gm3+ (auth_level 3)

gm3 is Coder, and a coder writes code. That is a decision about trust, not a
gap: verb code is ordinary Python in the server's process, so whoever can
write a verb can do anything the server account can. Grant gm3 to people you
would trust with the machine.

It was gm5 for part of 2026-08-26, while the ownership model was being built.
Ownership is what stops a coder touching other people's things -- their own
verbs run as them, so `auth` (owned by #0, perms 'rc') refuses them -- but it
cannot stop a verb that means harm, and pretending otherwise would be worse
than saying this plainly.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

import re

raw = (argstr or '').strip()
head, sep, tail = raw.partition(' with ')
spec = head.strip()
opts = tail.strip() if sep else ''

if not spec or '.' not in spec:
    pobj.msg('Usage: @adverb <object>.<name[(min)][,...]> [with <perms> [base] [min=N] [auth=N]]')
    pobj.msg('Example: @adverb #43.look,l')
    pobj.msg('Example: @adverb #2.examine(3),look(1),l')
    pobj.msg('Example: @adverb #2.examine,x with rx min=3')
else:
    obj_part, name_part = spec.rsplit('.', 1)

    candidates = list(pobj.contents)
    if pobj.location:
        candidates += list(pobj.location.contents)
    target = bmatch(obj_part.strip(), pobj, candidates, db)
    if not target:
        pobj.msg(f"Object '{obj_part}' not found.")
    else:
        raw_names = [n.strip() for n in name_part.split(',') if n.strip()]
        names = []
        pat = re.compile(r'^(.+?)\((\d+)\)$')
        for rn in raw_names:
            m = pat.match(rn)
            if m:
                names.append((m.group(1), int(m.group(2))))
            else:
                names.append(rn)

        if not names:
            pobj.msg('No verb name specified.')
        else:
            perms = 'rx'
            ptype = 'moo.verb_types.MasterVerb'
            mn = None
            auth_val = 0
            if opts:
                for p in opts.split():
                    if p == 'base':
                        ptype = 'moo.verb_types.BaseVerb'
                    elif p.startswith('min='):
                        if not p[4:].isdigit():
                            pobj.msg("min= wants a number, not '%s'." % p[4:])
                            return
                        mn = int(p[4:])
                    elif p.startswith('auth='):
                        if not p[5:].isdigit():
                            pobj.msg("auth= wants a number, not '%s'." % p[5:])
                            return
                        auth_val = int(p[5:])
                    elif p and all(c in 'rwxdc' for c in p):
                        perms = p
                    else:
                        pobj.msg("I don't know the option '%s'." % p)
                        return

            is_hidden = 'hidden' in switches or 'hide' in switches
            add_verb(target, names, perms=perms, parent_type=ptype, min=mn, hidden=is_hidden, auth=auth_val)

            import os
            verb_path = getattr(db.get_object(39), 'moo_verb_path', None)
            if verb_path:
                from moo.verb_loader import expand_verb_path
                base_path = expand_verb_path(verb_path)
                obj_dir = os.path.join(base_path, str(target.objnum))
                if not os.path.isdir(obj_dir):
                    os.makedirs(obj_dir, exist_ok=True)
                    for v in target.verbs:
                        vn = v.names[0] if v.names else None
                        if vn and v.code:
                            try:
                                with open(os.path.join(obj_dir, vn + '.py'), 'w') as f:
                                    f.write(v.code)
                            except Exception:
                                pass
                primary = names[0]
                vn = primary[0] if isinstance(primary, tuple) else primary
                stub_path = os.path.join(obj_dir, vn + '.py')
                if not os.path.isfile(stub_path):
                    try:
                        with open(stub_path, 'w') as f:
                            f.write(f'# Verb: {vn} on #{target.objnum}:{target.noun}\n')
                    except Exception:
                        pass

            parts = []
            for n in names:
                if isinstance(n, tuple):
                    parts.append(f'{n[0]}(min={n[1]})')
                elif mn is not None:
                    parts.append(f'{n}(min={mn})')
                else:
                    parts.append(n)
            desc = ', '.join(parts)
            extras = []
            if ptype != 'moo.verb_types.MasterVerb':
                extras.append('base')
            if is_hidden:
                extras.append('hidden')
            if auth_val:
                extras.append(f'auth={auth_val}')
            tag = f" ({' '.join(extras)})" if extras else ''
            pobj.msg(f"Verb [{desc}] added to &<245>#{target.objnum}:{target.name}&n perms={perms}{tag}")
