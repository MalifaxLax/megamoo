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
    @adverb #7.look,l
    @adverb #2.examine(3),look(1),l
    @adverb #2.examine,x with rx min=3
    @adverb #15.reset with rwx base
    @adverb/hidden #5.at_post_move
    @adverb #3.@telq with rx auth=3

Abbrev:  @adverb=4
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

import re

# Parse argstr, the full unsplit argument string, rather than the
# parser's dobj/prep/iobj.
#
# '=' is a preposition, so `@adverb #3.x with rx auth=3` was split at the
# '=' before this verb ran: prep was '=', never 'with', and the whole
# remainder arrived as one blob that became the verb's *name*.  It
# created `x with rx auth=3` and reported success.  Reading argstr sees
# what was typed, so options containing '=' work as documented.
raw = (argstr or '').strip()
head, sep, tail = raw.partition(' with ')
spec = head.strip()
opts = tail.strip() if sep else ''

# Validate input: must contain a dot to separate object from verb name(s)
if not spec or '.' not in spec:
    pobj.msg('Usage: @adverb <object>.<name[(min)][,...]> [with <perms> [base] [min=N] [auth=N]]')
    pobj.msg('Example: @adverb #7.look,l')
    pobj.msg('Example: @adverb #2.examine(3),look(1),l')
    pobj.msg('Example: @adverb #2.examine,x with rx min=3')
else:
    # Split object reference from verb name(s) at the last dot
    obj_part, name_part = spec.rsplit('.', 1)

    # Build candidate list and match the target object
    candidates = list(pobj.contents)
    if pobj.location:
        candidates += list(pobj.location.contents)
    target = bmatch(obj_part.strip(), pobj, candidates, db)
    if not target:
        pobj.msg(f"Object '{obj_part}' not found.")
    else:
        # Parse comma-separated verb names, each optionally with (min_length)
        raw_names = [n.strip() for n in name_part.split(',') if n.strip()]
        names = []
        pat = re.compile(r'^(.+?)\((\d+)\)$')
        for rn in raw_names:
            m = pat.match(rn)
            if m:
                # Name with explicit min abbreviation length
                names.append((m.group(1), int(m.group(2))))
            else:
                names.append(rn)

        if not names:
            pobj.msg('No verb name specified.')
        else:
            # Parse options: perms string, base flag, global min
            perms = 'rx'
            ptype = 'moo.verb_types.MasterVerb'
            mn = None
            auth_val = 0
            if opts:
                for p in opts.split():
                    if p == 'base':
                        ptype = 'moo.verb_types.BaseVerb'
                    elif p.startswith('min='):
                        # Reported, not raised. An unguarded int() died on
                        # the server's generic handler, so a typo answered
                        # "Do what?" -- which reads as "no such command"
                        # rather than "that is not a number".
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
                        # Anything unrecognised used to become the perms
                        # string in silence: `with rwx junk` set perms to
                        # 'junk' and the verb looked fine until something
                        # tried to honour it.
                        pobj.msg("I don't know the option '%s'." % p)
                        return

            # Add the verb to the target object
            is_hidden = 'hidden' in switches or 'hide' in switches
            add_verb(target, names, perms=perms, parent_type=ptype, min=mn, hidden=is_hidden, auth=auth_val)

            # Ensure per-object directory exists and write verb file
            import os
            verb_path = getattr(db.get_object(8), 'moo_verb_path', None)
            if verb_path:
                from moo.verb_loader import expand_verb_path
                base_path = expand_verb_path(verb_path)
                obj_dir = os.path.join(base_path, str(target.objnum))
                if not os.path.isdir(obj_dir):
                    os.makedirs(obj_dir, exist_ok=True)
                    # Export all existing verbs on this object
                    for v in target.verbs:
                        vn = v.names[0] if v.names else None
                        if vn and v.code:
                            try:
                                with open(os.path.join(obj_dir, vn + '.py'), 'w') as f:
                                    f.write(v.code)
                            except Exception:
                                pass
                # Write a stub file for the new verb
                primary = names[0]
                vn = primary[0] if isinstance(primary, tuple) else primary
                stub_path = os.path.join(obj_dir, vn + '.py')
                if not os.path.isfile(stub_path):
                    try:
                        with open(stub_path, 'w') as f:
                            f.write(f'# Verb: {vn} on #{target.objnum}:{target.noun}\n')
                    except Exception:
                        pass

            # Build confirmation message showing names and min lengths
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
